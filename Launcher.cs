// Plain .NET launcher; no embedded archive, updater or elevation.
// GPL-3.0. See LICENSE. Author: private0516.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Mesh Converter")]
[assembly: AssemblyDescription("Transparent Python application launcher")]
[assembly: AssemblyCompany("private0516")]
[assembly: AssemblyProduct("Mesh Converter ALPHA 1.0")]
[assembly: AssemblyCopyright("private0516")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyInformationalVersion("ALPHA 1.0")]

internal static class Launcher
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);

    [STAThread]
    private static int Main(string[] args)
    {
        bool cli = args.Length > 0;
        if (cli) AttachConsole(0xffffffff);
        LauncherLog log = null;
        try
        {
            string appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string logDirectory = Path.Combine(appData, "private0516", "MeshConverter", "logs");
            log = new LauncherLog(logDirectory, cli);
            if (args.Length > 0 && (args[0] == "--help" || args[0] == "-h"))
            {
                log.Write("Mesh Converter ALPHA 1.0 / private0516", false);
                log.Write("No arguments: open the desktop UI.", false);
                log.Write("--cli [arguments]       Run the batch converter; use --cli --help.", false);
                log.Write("--inventory [arguments] Run the read-only corpus inventory.", false);
                log.Write("--validate [arguments]  Run the isolated sample validation tool.", false);
                log.Write("--self-test PATH        Run the application's integration self-test.", false);
                log.Write("Other arguments are forwarded unchanged to app/app.py.", false);
                log.Write("Logs: " + logDirectory, false);
                return 0;
            }
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "python.exe");
            string scriptName = "app.py";
            int skip = 0;
            if (args.Length > 0)
            {
                if (args[0] == "--cli") { scriptName = "batch_nif.py"; skip = 1; }
                if (args[0] == "--inventory") { scriptName = "corpus_inventory.py"; skip = 1; }
                if (args[0] == "--validate") { scriptName = "validate_samples.py"; skip = 1; }
            }
            string script = Path.Combine(root, "app", scriptName);
            if (!File.Exists(python) || !File.Exists(script))
                throw new FileNotFoundException("The program folder is incomplete. Keep MeshConverter.exe together with app, runtime and vendor folders.");
            log.Write("Mesh Converter ALPHA 1.0 - transparent folder distribution", false);
            log.Write("Runtime: " + python, false);
            log.Write("Entry: " + scriptName, false);
            int code = LauncherProcess.Run(root, python, script, args, skip, log, null);
            if (code != 0 && !cli)
                MessageBox.Show("Mesh Converter could not complete startup.\n\nSee the log for details:\n" + log.PathName + "\n\nMicrosoft Edge WebView2 Runtime must already be installed.", "Mesh Converter", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return code;
        }
        catch (Exception error)
        {
            if (log != null) log.Write(error.ToString(), true);
            if (!cli) MessageBox.Show(error.Message + "\n\nLog: " + (log == null ? "unavailable" : log.PathName), "Mesh Converter", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally { if (log != null) log.Dispose(); }
    }
}

// Identical support is included in both independent launcher sources.
// The job controls lifetime; it is not a filesystem or privilege sandbox.
internal sealed class LauncherLog : IDisposable
{
    internal const int MaxRecordChars = 4096;
    internal const int MaxLogBytes = 8 * 1024 * 1024;
    private readonly object sync = new object();
    private readonly FileStream stream;
    private readonly bool console;
    private int written;
    private bool capped;
    internal readonly string PathName;

    internal LauncherLog(string directory, bool consoleOutput)
    {
        Directory.CreateDirectory(directory);
        PathName = Path.Combine(directory, "launcher-" + DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff") + "-" + Process.GetCurrentProcess().Id + "-" + Guid.NewGuid().ToString("N") + ".log");
        stream = new FileStream(PathName, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
        console = consoleOutput;
    }

    internal void Write(string value, bool error)
    {
        if (value == null) return;
        if (value.Length > MaxRecordChars) value = value.Substring(0, MaxRecordChars) + " [record truncated]";
        byte[] bytes = Encoding.UTF8.GetBytes(value + Environment.NewLine);
        lock (sync)
        {
            if (capped) return;
            // Reserve space for one terminal marker, including its newline.
            if (written + bytes.Length > MaxLogBytes - 128)
            {
                value = "[launcher log limit reached; further output is drained without retention]";
                bytes = Encoding.UTF8.GetBytes(value + Environment.NewLine);
                capped = true;
            }
            try { stream.Write(bytes, 0, bytes.Length); stream.Flush(); }
            catch (IOException) { capped = true; }
            catch (UnauthorizedAccessException) { capped = true; }
            written += bytes.Length;
            if (console)
            {
                try { if (error) Console.Error.WriteLine(value); else Console.Out.WriteLine(value); }
                catch (IOException) { }
            }
        }
    }

    internal void Pump(StreamReader reader, bool error)
    {
        // ReadLine/BeginOutputReadLine can allocate an unbounded record.
        char[] buffer = new char[2048];
        StringBuilder line = new StringBuilder(MaxRecordChars);
        bool truncated = false;
        try
        {
            int count;
            while ((count = reader.Read(buffer, 0, buffer.Length)) != 0)
            {
                for (int i = 0; i < count; i++)
                {
                    char c = buffer[i];
                    if (c == '\n')
                    {
                        Write(line.ToString().TrimEnd('\r') + (truncated ? " [record truncated]" : ""), error);
                        line.Length = 0;
                        truncated = false;
                    }
                    else if (line.Length < MaxRecordChars) line.Append(c);
                    else truncated = true;
                }
            }
            if (line.Length != 0 || truncated) Write(line.ToString() + (truncated ? " [record truncated]" : ""), error);
        }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
    }

    public void Dispose() { lock (sync) { capped = true; stream.Dispose(); } }
}

internal sealed class LauncherJob : IDisposable
{
    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimits
    {
        internal long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        internal uint LimitFlags;
        internal UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        internal uint ActiveProcessLimit;
        internal UIntPtr Affinity;
        internal uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters { internal ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimits
    {
        internal BasicLimits BasicLimitInformation;
        internal IoCounters IoInfo;
        internal UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int informationClass, ref ExtendedLimits information, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);
    private IntPtr handle;

    internal LauncherJob()
    {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle == IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Could not create the application lifetime job.");
        ExtendedLimits limits = new ExtendedLimits();
        limits.BasicLimitInformation.LimitFlags = 0x00002000; // KILL_ON_JOB_CLOSE
        if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))))
        {
            int error = Marshal.GetLastWin32Error();
            Dispose();
            throw new System.ComponentModel.Win32Exception(error, "Could not configure the application lifetime job.");
        }
    }

    internal void Assign(Process process)
    {
        if (!AssignProcessToJobObject(handle, process.Handle))
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Could not assign the application to its lifetime job. Startup was stopped before loading the application.");
    }

    public void Dispose()
    {
        if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
    }
}

internal static class LauncherProcess
{
    // Only the trusted Python standard library is loaded before the parent
    // assigns the child to its job. The application starts after the gate opens.
    // This avoids the Start()/AssignProcessToJobObject descendant-escape race.
    private const string Bootstrap =
        "import ctypes,sys\n" +
        "k=ctypes.WinDLL('kernel32',use_last_error=True)\n" +
        "k.OpenEventW.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_wchar_p]\n" +
        "k.OpenEventW.restype=ctypes.c_void_p\n" +
        "k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]\n" +
        "k.WaitForSingleObject.restype=ctypes.c_uint32\n" +
        "k.CloseHandle.argtypes=[ctypes.c_void_p]\n" +
        "h=k.OpenEventW(0x100000,False,sys.argv[1])\n" +
        "if not h: raise OSError(ctypes.get_last_error(),'Launcher startup gate unavailable')\n" +
        "r=k.WaitForSingleObject(h,30000)\n" +
        "k.CloseHandle(h)\n" +
        "if r!=0: sys.exit(125)\n" +
        "sys.argv=sys.argv[2:]\n" +
        "import runpy\n" +
        "runpy.run_path(sys.argv[0],run_name='__main__')\n";

    // Windows CommandLineToArgvW quoting, including trailing backslashes.
    internal static string Quote(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') result.Append('\\', slashes * 2 + 1);
            else result.Append('\\', slashes);
            result.Append(c);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    private static void PrepareEnvironment(ProcessStartInfo start, string root)
    {
        List<string> remove = new List<string>();
        foreach (string key in start.EnvironmentVariables.Keys)
            if (key.StartsWith("PYTHON", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("QT_PLUGIN_PATH", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("QT_QPA_PLATFORM_PLUGIN_PATH", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("QML2_IMPORT_PATH", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("QML_IMPORT_PATH", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("QTWEBENGINEPROCESS_PATH", StringComparison.OrdinalIgnoreCase) ||
                key.Equals("QTWEBENGINE_CHROMIUM_FLAGS", StringComparison.OrdinalIgnoreCase)) remove.Add(key);
        foreach (string key in remove) start.EnvironmentVariables.Remove(key);
        // Keep normal Qt rendering preferences (for example QT_OPENGL) intact.
        // Codec paths are absolute; app-controlled and system DLL directories
        // are sufficient and avoid inheriting unrelated tool folders from PATH.
        string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        start.EnvironmentVariables["PATH"] = String.Join(";", new string[] {
            Path.Combine(root, "runtime"), Path.Combine(root, "runtime", "DLLs"),
            Path.Combine(root, "vendor", "PySide6"), Environment.SystemDirectory, windows });
    }

    internal static int Run(string root, string python, string script, string[] args, int skip, LauncherLog log, string configPath)
    {
        string gateName = "Local\\private0516-launch-" + Guid.NewGuid().ToString("N");
        using (EventWaitHandle gate = new EventWaitHandle(false, EventResetMode.ManualReset, gateName))
        using (LauncherJob job = new LauncherJob())
        using (Process process = new Process())
        {
            List<string> arguments = new List<string>(new string[] { "-I", "-B", "-X", "utf8", "-c", Bootstrap, gateName, script });
            for (int i = skip; i < args.Length; i++) arguments.Add(args[i]);
            ProcessStartInfo start = new ProcessStartInfo(python, String.Join(" ", arguments.ConvertAll(Quote).ToArray()));
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
            PrepareEnvironment(start, root);
            if (configPath != null) start.EnvironmentVariables["TEXTURE_CONVERTER_CONFIG"] = configPath;
            process.StartInfo = start;
            process.Start();
            try { job.Assign(process); }
            catch
            {
                try { if (!process.HasExited) process.Kill(); }
                catch (InvalidOperationException) { }
                throw;
            }
            Thread stdout = new Thread(delegate() { log.Pump(process.StandardOutput, false); });
            Thread stderr = new Thread(delegate() { log.Pump(process.StandardError, true); });
            stdout.IsBackground = true;
            stderr.IsBackground = true;
            stdout.Start();
            stderr.Start();
            gate.Set();
            process.WaitForExit();
            int code = process.ExitCode;
            // Close owned descendants before joining readers: a stale child
            // must not hold inherited stdout/stderr pipes open indefinitely.
            job.Dispose();
            if (!stdout.Join(5000)) process.StandardOutput.Close();
            if (!stderr.Join(5000)) process.StandardError.Close();
            log.Write("Process exit code: " + code, false);
            return code;
        }
    }
}
