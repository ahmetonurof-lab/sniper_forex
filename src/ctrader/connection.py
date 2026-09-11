#!/usr/bin/env python
"""cTrader Open API Connection — D126 Adım A.2

D126 direktifindeki iskeletin GERÇEK SDK API'sine göre düzeltilmiş hali.

D126 iskeleti ile gerçek SDK arasındaki farklar (şeffaf beyan, AGENTS.md §3):
  1. `Client(host, port, client_id, client_secret, redirect_uri, access_token=...)`
     → GERÇEK: `Client(host, port, TcpProtocol)` — kimlik bilgileri ayrı mesajlarla
       gönderilir (ProtoOAApplicationAuthReq + ProtoOAAccountAuthReq).
  2. `self.client.start()` → GERÇEK: `self.client.startService()` (ClientService API).
  3. `Protobuf.ProtoHeartbeatEvent()` → GERÇEK: `Protobuf.get('ProtoHeartbeatEvent')`.
  4. Auth akışı D126'da eksikti: bağlantı sonrası uygulama auth → hesap auth sırası
     resmi örnekten (OpenApiPy samples) doğrulandı.

Reactor ayrı thread'de tek run; heartbeat watchdog 10s'de bir; reconcile
callFromThread ile ana thread ↔ reactor köprüsü.
"""

import json
import logging
import queue
import threading
import time
from pathlib import Path

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from twisted.internet import reactor

logger = logging.getLogger(__name__)

# Heartbeat aralığı (saniye) — D126: "en az 10 saniyede bir"
HEARTBEAT_INTERVAL_SEC = 10.0
# Reconcile/istek zaman aşımı (saniye)
REQUEST_TIMEOUT_SEC = 5.0

# Liveness penceresi (saniye) — İŞ-3 (cTrader reconnect paritesi).
# Sunucu ProtoHeartbeatEvent gönderir ve SDK idle >20s'de heartbeat yollar
# (docs/ctrader_openapi_official_research.md C5); sağlıklı bağlantıda
# mesaj akışı ~10-20s'de bir tazelenir. 60s = 3× idle-heartbeat aralığı:
# yanlış-pozitif riski olmadan half-open TCP'yi (19:31→20:46 kesintisi)
# dakikalar yerine ~1dk içinde yakalar.
STALE_MESSAGE_WINDOW_SEC = 60.0


class CTraderConnection:
    """cTrader Open API bağlantı yöneticisi.

    Reactor'u ayrı bir worker thread'de çalıştırır (tek run).
    Ana thread'den gelen istekler `callFromThread` ile reactor thread'ine
    köprülenir. Gelen mesajlar `event_queue`'ya konur.
    """

    def __init__(self, config, token_cache_path=None):
        self.config = config
        self.token_cache_path = Path(token_cache_path) if token_cache_path else None
        self.token_cache = self._load_token_cache()
        self.event_queue = queue.Queue()
        self._last_heartbeat_sent = 0.0
        self._connected = False
        self._stop = False
        self._thread = None
        # İŞ-3: son sunucu mesajının alındığı zaman (half-open TCP liveness
        # probu — is_stale). 0.0 = henüz hiç mesaj alınmadı.
        self._last_message_received = 0.0

        # GERÇEK SDK imzası: Client(host, port, protocol)
        self.client = Client(
            config["host"],
            EndPoints.PROTOBUF_PORT,
            TcpProtocol,
            numberOfMessagesToSendPerSecond=5,
        )

        # Callback'ler
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message_received)

    # ------------------------------------------------------------------
    # Yaşam döngüsü
    # ------------------------------------------------------------------
    def start(self):
        """Reactor'u ayrı thread'de başlat — tek run."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run_reactor, daemon=True)
        self._thread.start()

    def stop(self):
        """Bağlantıyı kapat (reconnect içeren ClientService durdurulur)."""
        self._stop = True
        try:
            reactor.callFromThread(self._do_stop)
        except Exception:
            pass

    def _run_reactor(self):
        """Worker thread gövdesi — reactor tek sefer çalışır."""
        self.client.startService()
        reactor.run(installSignalHandlers=False)

    def _do_stop(self):
        if self.client.running:
            self.client.stopService()
        if reactor.running:
            reactor.stop()

    # ------------------------------------------------------------------
    # Callback'ler (reactor thread'inde çalışır)
    # ------------------------------------------------------------------
    def _on_connected(self, client):
        self._connected = True
        self._last_message_received = time.time()
        self.event_queue.put(("CONNECTED", None))
        # İŞ-4/N2#27: reconnect observability — SOAK-2'de reconnect
        # izlenemezliği kök-nedenlerden biriydi (reconnect olup olmadığı
        # log'dan anlaşılamıyordu). Davranış değişmez — yalnız log.
        logger.info("ctrader_connected: account=%s", self.config.get("account_id"))
        # Bağlantı sonrası auth zinciri: uygulama auth → hesap auth
        self._send_application_auth()

    def _on_disconnected(self, client, reason):
        self._connected = False
        self.event_queue.put(("DISCONNECTED", str(reason)))
        # İŞ-4/N2#27: reconnect observability (davranış değişmez).
        logger.warning("ctrader_disconnected: reason=%s", reason)

    def _on_message_received(self, client, message):
        # İŞ-3: her sunucu mesajı liveness probunu tazeler (heartbeat dahil).
        self._last_message_received = time.time()
        payload_type = message.payloadType
        # Heartbeat'leri log'a boğma — sadece sayaç
        if payload_type == Protobuf.get_type("ProtoHeartbeatEvent"):
            self.event_queue.put(("HEARTBEAT", None))
            return
        try:
            extracted = Protobuf.extract(message)
            self.event_queue.put(("MESSAGE", extracted))
        except Exception as exc:  # pragma: no cover
            self.event_queue.put(("PARSE_ERROR", str(exc)))

    # ------------------------------------------------------------------
    # Auth zinciri
    # ------------------------------------------------------------------
    def _send_application_auth(self):
        """Uygulama kimliği doğrulaması (ProtoOAApplicationAuthReq)."""
        req = Protobuf.get("ProtoOAApplicationAuthReq")
        req.clientId = self.config["client_id"]
        req.clientSecret = self.config["client_secret"]
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addCallbacks(self._on_app_auth_res, self._on_auth_error)

    def _on_app_auth_res(self, result):
        self.event_queue.put(("APP_AUTH_RES", result))
        # Uygulama auth başarılı → hesap auth
        self._send_account_auth()

    def _send_account_auth(self):
        """Hesap doğrulaması (ProtoOAAccountAuthReq) — accessToken ile."""
        req = Protobuf.get("ProtoOAAccountAuthReq")
        req.ctidTraderAccountId = int(self.config["account_id"])
        req.accessToken = self.token_cache.get("access_token") or ""
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addCallbacks(self._on_account_auth_res, self._on_auth_error)

    def _on_account_auth_res(self, result):
        # D178: account-authorized gate — TCP/app-auth alone is NOT enough;
        # requests sent before this point get ProtoOAErrorRes
        # 'INVALID_REQUEST: Trading account is not authorized'.
        self._account_authorized = True
        self.event_queue.put(("ACCOUNT_AUTH_RES", result))

    def _on_auth_error(self, failure):
        self._account_authorized = False
        self.event_queue.put(("AUTH_ERROR", str(failure)))

    # ------------------------------------------------------------------
    # Heartbeat watchdog (D126: 10s'de bir klient göndermeli)
    # ------------------------------------------------------------------
    def send_heartbeat(self):
        """Ana thread'den çağrılır — callFromThread ile reactor'a köprülenir."""
        now = time.time()
        if now - self._last_heartbeat_sent >= HEARTBEAT_INTERVAL_SEC:
            self._last_heartbeat_sent = now
            try:
                reactor.callFromThread(self._do_send_heartbeat)
            except Exception:
                pass

    def _do_send_heartbeat(self):
        self.client.send(Protobuf.get("ProtoHeartbeatEvent"))

    # ------------------------------------------------------------------
    # Reconcile (D126: callFromThread ile)
    # ------------------------------------------------------------------
    def reconcile(self):
        """Ana thread'den çağrılır — hesap durumunu sunucudan yeniden kurar."""
        reactor.callFromThread(self._do_reconcile)

    def _do_reconcile(self):
        req = Protobuf.get("ProtoOAReconcileReq")
        req.ctidTraderAccountId = int(self.config["account_id"])
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addErrback(lambda f: self.event_queue.put(("RECONCILE_ERROR", str(f))))

    # ------------------------------------------------------------------
    # Sembol keşfi (Adım A.3)
    # ------------------------------------------------------------------
    def request_symbols_list(self, include_archived=False):
        """ProtoOASymbolsListReq — sembol listesi iste (BTCUSD symbolId için)."""
        req = Protobuf.get("ProtoOASymbolsListReq")
        req.ctidTraderAccountId = int(self.config["account_id"])
        req.includeArchivedSymbols = include_archived
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addErrback(lambda f: self.event_queue.put(("SYMBOLS_ERROR", str(f))))
        return deferred

    # ------------------------------------------------------------------
    # Veri-istekleri (İş-4a — D155): trendbar + spot abonelik.
    # Yanıtlar event_queue'ya MESSAGE olarak düşer (mevcut
    # _on_message_received yolu); hata(errback) TRENDBARS_ERROR/SPOTS_ERROR
    # etiketiyle. data_adapter bu kuyruğu tüketir.
    # ------------------------------------------------------------------
    def request_trendbars(self, symbol_id, period, from_ms, to_ms, count=None):
        """ProtoOAGetTrendbarsReq — geçmiş M1 trendbarları (İş-4a).

        Rate limit: 5 geçmiş-istek/sn/connection (resmi dok).
        Yanıt: ProtoOAGetTrendbarsRes (event_queue, MESSAGE).
        """
        req = Protobuf.get("ProtoOAGetTrendbarsReq")
        req.ctidTraderAccountId = int(self.config["account_id"])
        req.symbolId = int(symbol_id)
        req.period = int(period)
        req.fromTimestamp = int(from_ms)
        req.toTimestamp = int(to_ms)
        if count is not None:
            req.count = int(count)
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addErrback(lambda f: self.event_queue.put(("TRENDBARS_ERROR", str(f))))
        return deferred

    def subscribe_spots(self, symbol_id):
        """ProtoOASubscribeSpotsReq — spot fiyat aboneliği (İş-4a).

        subscribeToSpotTimestamp=True: ProtoOASpotEvent.timestamp alanı
        dolu gelir (adapter'ın quote-age kontrolü için gerekli).
        Yanıt: ProtoOASubscribeSpotsRes + ProtoOASpotEvent akışı.
        """
        req = Protobuf.get("ProtoOASubscribeSpotsReq")
        req.ctidTraderAccountId = int(self.config["account_id"])
        req.symbolId.append(int(symbol_id))
        req.subscribeToSpotTimestamp = True
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addErrback(lambda f: self.event_queue.put(("SPOTS_ERROR", str(f))))
        return deferred

    # ------------------------------------------------------------------
    # Emir gönderimi (D170-§3-Adım-③-B — send_order ince-ek).
    # Payload CTraderExecution tarafından hazırlanır (src/ctrader/
    # execution.py); bu katman yalnızca ProtoOANewOrderReq'e çevirir.
    # Yanıtlar (ProtoOAExecutionEvent / ProtoOAErrorRes) mevcut
    # _on_message_received yoluyla ("MESSAGE", extracted) olarak
    # event_queue'ya düşer; errback ORDER_ERROR etiketiyle.
    # NOT: Absolute stopLoss/takeProfit MARKET emirde desteklenmez —
    # relative* alanları CTraderExecution tarafında hesaplanır (D169-§4).
    # ------------------------------------------------------------------
    # ProtoOAOrderType: MARKET=1; ProtoOATradeSide: BUY=1, SELL=2.
    ORDER_TYPE_MARKET = 1
    TRADE_SIDE_BUY = 1
    TRADE_SIDE_SELL = 2

    def send_order(self, payload):
        """ProtoOANewOrderReq — MARKET emir (volume 0.01-unit çarpanlı).

        payload (dict, CTraderExecution üretimi):
            symbol_id: int
            trade_side: "BUY" | "SELL"
            volume: int (protocol volume; lot x contract_size x 100)
            relativeStopLoss / relativeTakeProfit: int (scale=10^pipPosition)
            clientOrderId: str (<=50 char; kapı-5)
            label: str
        Ana thread'den çağrılır — callFromThread ile reactor'a köprülenir.
        """
        reactor.callFromThread(self._do_send_order, dict(payload))

    def _do_send_order(self, payload):
        req = Protobuf.get("ProtoOANewOrderReq")
        req.ctidTraderAccountId = int(self.config["account_id"])
        req.symbolId = int(payload["symbol_id"])
        req.orderType = self.ORDER_TYPE_MARKET
        req.tradeSide = (
            self.TRADE_SIDE_BUY if payload.get("trade_side") == "BUY" else self.TRADE_SIDE_SELL
        )
        req.volume = int(payload["volume"])
        req.relativeStopLoss = int(payload["relativeStopLoss"])
        req.relativeTakeProfit = int(payload["relativeTakeProfit"])
        req.clientOrderId = str(payload["clientOrderId"])
        req.label = str(payload.get("label") or "SNIPER_FOREX")
        deferred = self.client.send(req, responseTimeoutInSeconds=REQUEST_TIMEOUT_SEC)
        deferred.addErrback(lambda f: self.event_queue.put(("ORDER_ERROR", str(f))))
        return deferred

    # ------------------------------------------------------------------
    # Token cache
    # ------------------------------------------------------------------
    def _load_token_cache(self):
        if self.token_cache_path and self.token_cache_path.exists():
            try:
                return json.loads(self.token_cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"access_token": None, "refresh_token": None, "expires_at": None}

    def save_token_cache(self):
        """Token cache'i diske yaz (access_token doldurulduğunda çağrılır)."""
        if self.token_cache_path:
            self.token_cache_path.write_text(
                json.dumps(self.token_cache, indent=2), encoding="utf-8"
            )

    # ------------------------------------------------------------------
    # Durum
    # ------------------------------------------------------------------
    @property
    def is_connected(self):
        return self._connected

    @property
    def account_authorized(self):
        """D178: True only after ProtoOAAccountAuthRes (production callback
        path). TCP connect + app-auth do NOT authorize trading-account
        requests — the adapter's ensure_connected waits on this gate."""
        return getattr(self, "_account_authorized", False)

    def is_stale(self, timeout_sec: float = STALE_MESSAGE_WINDOW_SEC) -> bool:
        """İŞ-3: half-open TCP liveness probu.

        True when no server message has been received within the window.
        The callback flag (`is_connected`) stays True on a half-open
        connection (network drop without FIN/RST → Twisted connectionLost
        never fires → the passive ClientService retry policy never
        engages — the 19:31→20:46 outage root cause). This probe lets the
        adapter detect the dead connection and trigger an ACTIVE reconnect.

        Duck-typed contract: fakes without this method are never stale
        (adapter `_conn_stale` returns False).
        """
        if self._last_message_received <= 0:
            return not self._connected
        return (time.time() - self._last_message_received) > timeout_sec

    def reconnect(self, max_attempts: int = 3) -> bool:
        """İŞ-3: aktif reconnect — MT5 `reconnect(max_attempts=3)` paritesi.

        The ClientService retry policy only reconnects on a DETECTED
        disconnect; a half-open TCP connection never fires connectionLost,
        so the passive policy never recovers (19:31→20:46: ~75 min dead).
        This method force-restarts the ClientService (bypassing
        `Client.stopService`'s isConnected guard) and waits bounded for
        connected + account-authorized.

        Returns True when reconnected (connected AND account-authorized)
        within the bounded wait, False otherwise.
        """
        # İŞ-4/N2#27: reconnect observability (davranış değişmez).
        logger.warning("ctrader_reconnect_start: max_attempts=%d", max_attempts)
        if self._thread is None or not self._thread.is_alive():
            logger.warning("ctrader_reconnect_no_thread")
            return False
        try:
            reactor.callFromThread(self._do_reconnect)
        except Exception:
            logger.warning("ctrader_reconnect_call_failed", exc_info=True)
            return False
        deadline = time.monotonic() + min(max_attempts, 5) * 2.0
        while time.monotonic() < deadline:
            if self._connected and self._account_authorized:
                logger.info("ctrader_reconnect_ok")
                return True
            time.sleep(0.2)
        ok = self._connected and self._account_authorized
        if not ok:
            logger.warning("ctrader_reconnect_failed")
        return ok

    def _do_reconnect(self):
        """Reactor thread'inde: ClientService'i zorla durdur + yeniden başlat.

        `Client.stopService` override'ı `isConnected` guard'ına bakar
        (disconnected iken no-op) — bu yüzden doğrudan
        `ClientService.stopService` çağrılır (guard bypass). Auth zinciri
        yeni bağlantıda yeniden çalışır (app auth → account auth).
        """
        from twisted.application.internet import ClientService

        # İŞ-4/N2#27: reconnect observability (davranış değişmez).
        logger.warning("ctrader_do_reconnect: stopping ClientService")
        try:
            d = ClientService.stopService(self.client)
        except Exception:
            d = None
        self._connected = False
        self._account_authorized = False
        self._last_message_received = 0.0
        if d is not None and hasattr(d, "addCallback"):
            d.addCallback(lambda _: self.client.startService())
            d.addErrback(lambda _: self.client.startService())
        else:
            self.client.startService()

    def drain_events(self):
        """Ana thread'den event kuyruğunu boşalt — (tip, veri) listesi döner.

        vulture-fix (D148): ``timeout`` parametresi hiçbir çağrı-yerinde
        kullanılmıyordu (repo-taraması: tek-referans bu tanım) ve gövde
        onu okumuyordu (get_nowait non-blocking). Ölü-param silindi —
        davranış değişmedi (parametre zaten etkisizdi)."""
        events = []
        try:
            while True:
                events.append(self.event_queue.get_nowait())
        except queue.Empty:
            pass
        return events
