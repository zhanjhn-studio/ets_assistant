// =============================================================================
//  winmm_hook.cpp  ——  E听说 winmm.dll 劫持框架（实验性 / 高风险）
//
//  ⚠️ 免责声明：
//  本文件仅供逆向工程教学与 Windows API Hook 技术研究，严禁用于考试作弊、
//  侵犯软件权益或任何违法违规用途。使用者须自行承担一切法律与纪律责任。
//  作者不对任何使用后果负责。请在理解风险并获授权的前提下研究本代码。
//
//  原理：利用 Windows DLL 搜索顺序，将本 DLL 以 winmm.dll 之名置于
//  C:\Program Files (x86)\ETS\ 下，劫持 E听说 对系统多媒体/计时 API 的调用。
//  所有真实导出均转发到系统原始 winmm.dll，仅对选定函数用 Detours 挂钩。
//
//  构建：需 MSVC + CMake + Detours。详见同目录 README.md。
// =============================================================================

#include <windows.h>
#include <detours/detours.h>
#include <string>
#include <fstream>

// ---------------------------------------------------------------------------
//  转发：把本 DLL 的所有 winmm 导出直接转发到同目录的 winmm_orig.dll
//  （build 脚本会从 System32 拷贝 winmm.dll 并重命名为 winmm_orig.dll，
//   这样转发目标稳定且不会递归加载自身。）
//  完整导出列表见同目录 real_winmm.def；此处用 pragma 声明转发，序号一致。
// ---------------------------------------------------------------------------
#pragma comment(linker, "/EXPORT:waveOutOpen=winmm_orig.waveOutOpen,@1")
#pragma comment(linker, "/EXPORT:waveOutClose=winmm_orig.waveOutClose,@2")
#pragma comment(linker, "/EXPORT:waveOutPrepareHeader=winmm_orig.waveOutPrepareHeader,@3")
#pragma comment(linker, "/EXPORT:waveOutWrite=winmm_orig.waveOutWrite,@4")
#pragma comment(linker, "/EXPORT:waveOutUnprepareHeader=winmm_orig.waveOutUnprepareHeader,@5")
#pragma comment(linker, "/EXPORT:waveInOpen=winmm_orig.waveInOpen,@6")
#pragma comment(linker, "/EXPORT:waveInClose=winmm_orig.waveInClose,@7")
#pragma comment(linker, "/EXPORT:waveInPrepareHeader=winmm_orig.waveInPrepareHeader,@8")
#pragma comment(linker, "/EXPORT:waveInAddBuffer=winmm_orig.waveInAddBuffer,@9")
#pragma comment(linker, "/EXPORT:waveInUnprepareHeader=winmm_orig.waveInUnprepareHeader,@10")
#pragma comment(linker, "/EXPORT:timeGetTime=winmm_orig.timeGetTime,@11")
#pragma comment(linker, "/EXPORT:timeSetEvent=winmm_orig.timeSetEvent,@12")
#pragma comment(linker, "/EXPORT:timeKillEvent=winmm_orig.timeKillEvent,@13")
#pragma comment(linker, "/EXPORT:timeBeginPeriod=winmm_orig.timeBeginPeriod,@14")
#pragma comment(linker, "/EXPORT:timeEndPeriod=winmm_orig.timeEndPeriod,@15")
#pragma comment(linker, "/EXPORT:PlaySoundW=winmm_orig.PlaySoundW,@16")
#pragma comment(linker, "/EXPORT:PlaySoundA=winmm_orig.PlaySoundA,@17")
#pragma comment(linker, "/EXPORT:sndPlaySoundW=winmm_orig.sndPlaySoundW,@18")
#pragma comment(linker, "/EXPORT:waveOutGetNumDevs=winmm_orig.waveOutGetNumDevs,@19")
#pragma comment(linker, "/EXPORT:waveInGetNumDevs=winmm_orig.waveInGetNumDevs,@20")

// ---------------------------------------------------------------------------
//  真实系统 winmm.dll 的延迟加载（避免递归加载自身）
// ---------------------------------------------------------------------------
static HMODULE g_realWinmm = nullptr;

static HMODULE GetRealWinmm() {
    if (!g_realWinmm) {
        // 直接从 System32 加载真正的 winmm，不走搜索顺序
        g_realWinmm = LoadLibraryW(L"C:\\Windows\\System32\\winmm.dll");
    }
    return g_realWinmm;
}

// ---------------------------------------------------------------------------
//  Detours 挂钩示例：timeGetTime（计时）
//  原 ETSToolbox 通过调整计时实现"节流/冻结"效果。此处仅作技术演示，
//  不内置任何具体作弊数值。
// ---------------------------------------------------------------------------
static DWORD (WINAPI *Real_timeGetTime)(void) = nullptr;

static DWORD WINAPI Hook_timeGetTime(void) {
    // 技术演示：原样调用真实函数。
    // 研究者可在此注入偏移/缩放逻辑（风险自负）。
    return Real_timeGetTime();
}

// ---------------------------------------------------------------------------
//  Detours 挂钩示例：waveOutOpen（音频输出）
// ---------------------------------------------------------------------------
static MMRESULT (WINAPI *Real_waveOutOpen)(
    LPHWAVEOUT phwo, UINT uDeviceID, LPCWAVEFORMATEX pwfx,
    DWORD dwCallback, DWORD dwInstance, DWORD fdwOpen) = nullptr;

static MMRESULT WINAPI Hook_waveOutOpen(
    LPHWAVEOUT phwo, UINT uDeviceID, LPCWAVEFORMATEX pwfx,
    DWORD dwCallback, DWORD dwInstance, DWORD fdwOpen) {
    // 技术演示：直接转发。可在此拦截音频流参数。
    return Real_waveOutOpen(phwo, uDeviceID, pwfx, dwCallback, dwInstance, fdwOpen);
}

// ---------------------------------------------------------------------------
//  安装 / 卸载挂钩
// ---------------------------------------------------------------------------
static void InstallHooks() {
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());

    if (auto p = (void*)GetProcAddress(GetRealWinmm(), "timeGetTime"))
        DetourAttach(&(PVOID&)Real_timeGetTime, Hook_timeGetTime);
    if (auto p = (void*)GetProcAddress(GetRealWinmm(), "waveOutOpen"))
        DetourAttach(&(PVOID&)Real_waveOutOpen, Hook_waveOutOpen);

    DetourTransactionCommit();
}

static void RemoveHooks() {
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    if (Real_timeGetTime) DetourDetach(&(PVOID&)Real_timeGetTime, Hook_timeGetTime);
    if (Real_waveOutOpen) DetourDetach(&(PVOID&)Real_waveOutOpen, Hook_waveOutOpen);
    DetourTransactionCommit();
}

// ---------------------------------------------------------------------------
//  DLL 入口
// ---------------------------------------------------------------------------
BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        GetRealWinmm();   // 预加载真实 winmm
        InstallHooks();
        break;
    case DLL_PROCESS_DETACH:
        RemoveHooks();
        if (g_realWinmm) FreeLibrary(g_realWinmm);
        break;
    }
    return TRUE;
}
