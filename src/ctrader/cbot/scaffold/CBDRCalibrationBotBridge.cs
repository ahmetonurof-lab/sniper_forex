using System;
using Python.Runtime;

namespace cAlgo.Robots;

internal class CBDRCalibrationBotBridge : BaseBridge
{
    private readonly SafeExecuteMethodProxy _onStartProxy;
    private readonly SafeExecuteMethodProxy _onTickProxy;
    private readonly SafeExecuteMethodProxy _onStopProxy;
    private readonly SafeExecuteMethodProxy _onBarProxy;
    private readonly SafeExecuteMethodProxy _onBarClosedProxy;

    public CBDRCalibrationBotBridge(PyObject objectInstance) : base(objectInstance)
    {
        _onStartProxy = new SafeExecuteMethodProxy(objectInstance, "on_start");
        _onTickProxy = new SafeExecuteMethodProxy(objectInstance, "on_tick");
        _onStopProxy = new SafeExecuteMethodProxy(objectInstance, "on_stop");
        _onBarProxy = new SafeExecuteMethodProxy(objectInstance, "on_bar");
        _onBarClosedProxy = new SafeExecuteMethodProxy(objectInstance, "on_bar_closed");
    }

    public void OnStart()
    {
        _onStartProxy.Invoke();
    }

    public void OnTick()
    {
        _onTickProxy.Invoke();
    }

    public void OnStop()
    {
        _onStopProxy.Invoke();
    }

    public void OnBar()
    {
        _onBarProxy.Invoke();
    }

    public void OnBarClosed()
    {
        _onBarClosedProxy.Invoke();
    }
}
