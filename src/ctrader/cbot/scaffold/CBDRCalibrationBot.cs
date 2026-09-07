using System;
using System.Runtime.InteropServices;
using Python.Runtime;
using cAlgo.API;
using cAlgo.Robots;

namespace cAlgo.Robots
{
    /// <summary>
    /// CBDR Calibration cBot — thin C# bridge that compiles for cTrader Automate.
    /// Python lifecycle is handled by cbdr_calibration_bot.py / core.py.
    /// Parameters are surfaced to the cTrader UI and optimizer.
    ///
    /// Deployment: MT5-EA style — one cBot instance attached per chart.
    /// The same code runs on each pair; cTrader supplies the per-pair symbol.
    /// </summary>
    public partial class CBDRCalibrationBot : Robot
    {
        private CBDRCalibrationBotBridge _pythonBridge;
        private PyObject _pyRobotInstance;
        private bool? _pythonIsSupported;

        private const string MainPythonFile = "cbdr_calibration_bot.py";

        protected override void OnStart()
        {
            if (!CanExecutePythonAlgorithm())
            {
                Stop();
                return;
            }

            EngineHelper.Initialize(this, Print);

            using (Py.GIL())
            {
                var code = EmbeddedResourceProvider.ReadText(MainPythonFile);
                var className = EngineHelper.GetClassName(code);

                using (var scope = Py.CreateScope())
                {
                    scope.Set("currentAssembly", System.Reflection.Assembly.GetExecutingAssembly());

                    try
                    {
                        scope.Exec(code);
                        if (!scope.Contains(className))
                        {
                            Print($"Error: Python class '{className}' not found in the module!");
                            throw new InvalidOperationException($"Python class '{className}' not found in the module");
                        }

                        dynamic pythonClass = scope.Get(className);
                        _pyRobotInstance = pythonClass();
                        _pythonBridge = new CBDRCalibrationBotBridge(_pyRobotInstance);

                        _pythonBridge.OnStart();
                    }
                    catch (Exception ex)
                    {
                        Print($"Error initializing Python: {ex.Message}\nStack trace: {ex.StackTrace}");
                        throw;
                    }
                }
            }
        }

        protected override void OnTick()
        {
            if (!CanExecutePythonAlgorithm() || _pythonBridge == null)
                return;

            using (Py.GIL())
                _pythonBridge.OnTick();
        }

        protected override void OnStop()
        {
            if (!CanExecutePythonAlgorithm() || _pythonBridge == null)
                return;

            using (Py.GIL())
                _pythonBridge.OnStop();
        }

        protected override void OnBar()
        {
            if (!CanExecutePythonAlgorithm() || _pythonBridge == null)
                return;

            using (Py.GIL())
                _pythonBridge.OnBar();
        }

        protected override void OnBarClosed()
        {
            if (!CanExecutePythonAlgorithm() || _pythonBridge == null)
                return;

            using (Py.GIL())
                _pythonBridge.OnBarClosed();
        }

        protected override void OnTimer()
        {
            if (!CanExecutePythonAlgorithm() || _pythonBridge == null)
                return;

            using (Py.GIL())
                _pythonBridge.OnTimer();
        }

        protected override void OnException(Exception exception)
        {
            if (!CanExecutePythonAlgorithm() || _pythonBridge == null)
                return;

            using (Py.GIL())
                _pythonBridge.OnException(exception);
        }

        protected override double GetFitness(GetFitnessArgs getFitnessArgs)
        {
            return 0;
        }

        private bool CanExecutePythonAlgorithm()
        {
            if (_pythonIsSupported == false)
                return false;

            if (_pythonIsSupported == true)
                return true;

            if (!IsPlatformSupported())
            {
                Print("Python algorithms are not supported in the current version of cTrader");
                _pythonIsSupported = false;
                return false;
            }

            _pythonIsSupported = true;
            return true;
        }

        private bool IsPlatformSupported()
        {
            var version = Application.Version;

            if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows) &&
                (version.Major > 5 || version.Major == 5 && version.Minor >= 4))
                return true;

            if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX) &&
                (version.Major > 5 || version.Major == 5 && version.Minor >= 7))
                return true;

            if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux) ||
                RuntimeInformation.IsOSPlatform(OSPlatform.FreeBSD))
                return true;

            return false;
        }
    }
}
