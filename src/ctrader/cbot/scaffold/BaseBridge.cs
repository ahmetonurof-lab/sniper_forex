// ---------------------------------------------------------------
// Spotware standard bridge — identical across all Python algo samples.
// Source: spotware/ctrader-python-algo-samples (MIT-licensed).
// DO NOT EDIT — regenerate from Spotware samples if upgrading.
// ---------------------------------------------------------------

using System;
using Python.Runtime;

namespace cAlgo.Robots;

internal abstract class BaseBridge
{
    private readonly SafeExecuteMethodProxy _onOnTimerProxy;
    private readonly SafeExecuteMethodProxy _onExceptionProxy;

    protected BaseBridge(PyObject objectInstance)
    {
        _onOnTimerProxy = new SafeExecuteMethodProxy(objectInstance, "on_timer");
        _onExceptionProxy = new SafeExecuteMethodProxy(objectInstance, "on_exception");
    }

    internal void OnTimer()
    {
        _onOnTimerProxy.Invoke();
    }

    internal void OnException(Exception exception)
    {
        _onExceptionProxy.Invoke(exception);
    }
}
