/* ==========================================================================
 * eSim.exe — native Windows entry point for eSim.
 *
 * A .bat launcher cannot carry an icon or version info, shows up in Windows
 * search as a bare script, and flashes a console on every start. This tiny
 * GUI-subsystem executable is what the Start-menu/desktop shortcuts (and
 * Windows search) point at instead. It mirrors esim.bat's environment setup
 * exactly, then hands off to the bundled python.
 *
 *   <root>\eSim.exe            (this file, at the install root)
 *   <root>\python\python.exe   <root>\src\frontEnd\Application.py   (+ log console)
 *
 * esim.bat stays in the install for terminal use; both must keep making the
 * same environment decisions (see esim.bat for the reasoning per entry).
 *
 * Args: everything is forwarded to Application.py. By default eSim launches
 * under python.exe in its OWN console, so its stdout/stderr log stream is
 * visible alongside the GUI -- the same experience as starting eSim from a
 * Linux terminal. `--no-console` restores the old silent pythonw launch (no
 * window); `--debug` is a redundant alias of the default now. `--doctor`
 * runs the toolchain report under `cmd /k` so it stays on screen after the
 * probe exits.
 * ========================================================================== */

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>

#define PATHCAP 4096            /* single dir / command fragments */
#define ENVCAP  65536           /* full PATH value */

static int file_exists(const wchar_t *p)
{
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static void append(wchar_t *dst, size_t cap, const wchar_t *src)
{
    size_t n = lstrlenW(dst);
    lstrcpynW(dst + n, src, (int)(cap - n));
}

static void fail(const wchar_t *msg)
{
    MessageBoxW(NULL, msg, L"eSim", MB_ICONERROR | MB_OK);
    ExitProcess(1);
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR pCmdLine, int nCmdShow)
{
    (void)hInst; (void)hPrev; (void)nCmdShow;

    /* --- install root = this exe's directory ---------------------------- */
    wchar_t root[PATHCAP];
    DWORD n = GetModuleFileNameW(NULL, root, PATHCAP);
    if (n == 0 || n >= PATHCAP)
        fail(L"Could not resolve the eSim install location.");
    for (int i = (int)n - 1; i >= 0; --i) {
        if (root[i] == L'\\') { root[i] = 0; break; }
    }

    wchar_t buf[PATHCAP];

    /* --- PATH: same precedence as esim.bat ------------------------------
     * bat prepends ngspice, then nghdl, then Program-Files KiCad, then the
     * bundled KiCad — so the final order (first match wins) is:
     *   bundled KiCad ; PF KiCad ; nghdl ngspice ; fallback ngspice ; old
     */
    wchar_t *newpath = (wchar_t *)LocalAlloc(LPTR, ENVCAP * sizeof(wchar_t));
    wchar_t *oldpath = (wchar_t *)LocalAlloc(LPTR, ENVCAP * sizeof(wchar_t));
    if (!newpath || !oldpath)
        fail(L"Out of memory building the eSim environment.");
    GetEnvironmentVariableW(L"PATH", oldpath, ENVCAP);

    wsprintfW(buf, L"%s\\tools\\kicad\\bin\\eeschema.exe", root);
    if (file_exists(buf)) {
        wsprintfW(buf, L"%s\\tools\\kicad\\bin;", root);
        append(newpath, ENVCAP, buf);
    }

    /* system-wide KiCad installs (old layout) as fallback */
    wchar_t pf[PATHCAP];
    if (GetEnvironmentVariableW(L"ProgramFiles", pf, PATHCAP) > 0) {
        wchar_t pattern[PATHCAP];
        wsprintfW(pattern, L"%s\\KiCad\\*", pf);
        WIN32_FIND_DATAW fd;
        HANDLE h = FindFirstFileW(pattern, &fd);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY))
                    continue;
                if (fd.cFileName[0] == L'.')
                    continue;
                wsprintfW(buf, L"%s\\KiCad\\%s\\bin\\eeschema.exe",
                          pf, fd.cFileName);
                if (file_exists(buf)) {
                    wsprintfW(buf, L"%s\\KiCad\\%s\\bin;", pf, fd.cFileName);
                    append(newpath, ENVCAP, buf);
                }
            } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
    }

    /* custom eSim ngspice (d_cosim/ivlng/ghdl.cm) over the official copy */
    wsprintfW(buf, L"%s\\tools\\nghdl\\install_dir\\bin\\ngspice.exe", root);
    if (file_exists(buf)) {
        wsprintfW(buf, L"%s\\tools\\nghdl\\install_dir\\bin;", root);
        append(newpath, ENVCAP, buf);
        wsprintfW(buf, L"%s\\tools\\nghdl\\install_dir\\share\\ngspice", root);
        SetEnvironmentVariableW(L"SPICE_LIB_DIR", buf);
    }

    wsprintfW(buf, L"%s\\tools\\ngspice\\bin;", root);
    append(newpath, ENVCAP, buf);

    append(newpath, ENVCAP, oldpath);
    SetEnvironmentVariableW(L"PATH", newpath);

    /* Application.py: skip its in-process env setup, ours is authoritative */
    SetEnvironmentVariableW(L"ESIM_ENV_READY", L"1");

    /* --- pick interpreter and build the command line --------------------- */
    /* Default is a visible log console (python.exe in its own window),
     * mirroring the Linux launch where eSim's stdout/stderr scroll in the
     * terminal it was started from. `--no-console` opts back out to the old
     * silent pythonw launch (no window). */
    int no_console = wcsstr(pCmdLine, L"--no-console") != NULL;
    int doctor     = wcsstr(pCmdLine, L"--doctor")     != NULL;
    int console    = !no_console;   /* GUI + log window unless opted out */

    wchar_t *cmd = (wchar_t *)LocalAlloc(LPTR, ENVCAP * sizeof(wchar_t));
    if (!cmd)
        fail(L"Out of memory building the eSim command line.");
    if (doctor) {
        /* keep the report on screen after the probe exits */
        wsprintfW(cmd,
            L"cmd.exe /k \"\"%s\\python\\python.exe\" "
            L"\"%s\\src\\frontEnd\\Application.py\" --doctor\"",
            root, root);
    } else {
        /* -u under the console: unbuffered stdout/stderr, so the log appears
         * line-by-line as it happens instead of in a lump when a pipe buffer
         * fills. pythonw (opt-out) has nowhere to print, so it is left plain. */
        wsprintfW(cmd, L"\"%s\\python\\%s\"%s \"%s\\src\\frontEnd\\Application.py\"",
                  root, console ? L"python.exe" : L"pythonw.exe",
                  console ? L" -u" : L"", root);
        if (*pCmdLine) {
            append(cmd, ENVCAP, L" ");
            append(cmd, ENVCAP, pCmdLine);
        }
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    /* Title the log window "eSim" instead of the raw python.exe path. */
    si.lpTitle = (wchar_t *)L"eSim \x2014 log";
    DWORD flags = (console || doctor) ? CREATE_NEW_CONSOLE : 0;
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, flags,
                        NULL, root, &si, &pi)) {
        fail(L"Could not start eSim.\n\n"
             L"The install may be damaged — python\\pythonw.exe was not "
             L"found next to eSim.exe. Reinstalling eSim should fix this.");
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
