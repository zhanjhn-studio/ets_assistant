# 启用/恢复 Windows 录音设备中的"立体声混音"（Stereo Mix）。
# 需要管理员权限才能修改默认录音设备（少数系统下）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File enable_stereo_mix.ps1 enable
#   powershell -ExecutionPolicy Bypass -File enable_stereo_mix.ps1 restore
#   powershell -ExecutionPolicy Bypass -File enable_stereo_mix.ps1 list
#
# ⚠️ 免责声明：本脚本仅供技术研究，严禁用于作弊。使用者自负责任。
#
# 实现说明：Win10/11 已移除 PolicyConfigVista 的 ProgID 注册，纯 PowerShell
# New-Object -ComObject 必然报 0x80040154。这里改用 C# 注入方式，显式声明
# IPolicyConfig 接口（vtable 含 ResetDeviceFormat）与正确的 CLSID
# {870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}，即可可靠调用 SetDefaultEndpoint。

param([string]$Mode = "enable")

$ErrorActionPreference = "Stop"

$code = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;

[Guid("a95664d2-9614-4f35-a746-de8db63617e6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int dwStateMask, out IMMDeviceCollection ppDevices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppEndpoint);
    int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string pwstrId, out IMMDevice ppDevice);
    int RegisterEndpointNotificationCallback(IntPtr pClient);
    int UnregisterEndpointNotificationCallback(IntPtr pClient);
}
[Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceCollection {
    int GetCount(out int pnNumDevices);
    int Item(int nDevice, out IMMDevice ppDevice);
}
[Guid("d666063f-1587-4e43-81f1-b948e807363f"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref Guid iid, int dwClsCtx, IntPtr pActivationParams, out IntPtr ppInterface);
    int OpenPropertyStore(int stgmAccess, out IPropertyStore ppStore);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string ppstrId);
    int GetState(out int pdwState);
}
[Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    int GetCount(out int cProps);
    int GetAt(int iProp, out PROPERTYKEY pkey);
    int GetValue([In] ref PROPERTYKEY key, out PROPVARIANT pv);
    int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
    int Commit();
}
[StructLayout(LayoutKind.Sequential)]
struct PROPERTYKEY { public Guid fmtid; public int pid; }
[StructLayout(LayoutKind.Sequential)]
struct PROPVARIANT { public ushort vt; public ushort wReserved1; public ushort wReserved2; public ushort wReserved3; public IntPtr data; }
[Guid("f8679f50-850a-41cf-9c72-430f290290c8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPolicyConfig {
    [PreserveSig] int GetMixFormat(string pszDeviceName, out IntPtr ppFormat);
    [PreserveSig] int GetDeviceFormat(string pszDeviceName, bool bDefault, out IntPtr ppFormat);
    [PreserveSig] int ResetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName);
    [PreserveSig] int SetDeviceFormat(string pszDeviceName, IntPtr pFormat, IntPtr pFormatDst);
    [PreserveSig] int GetProcessingPeriod(string pszDeviceName, bool bDefault, out long pmftDefault, out long pmftMin, out long pmftMax);
    [PreserveSig] int SetProcessingPeriod(string pszDeviceName, long pmftDefault, long pmftMin, long pmftMax);
    [PreserveSig] int GetShareMode(string pszDeviceName, out IntPtr pMode);
    [PreserveSig] int SetShareMode(string pszDeviceName, IntPtr mode);
    [PreserveSig] int GetPropertyValue(string pszDeviceName, out IntPtr key, out IntPtr pv);
    [PreserveSig] int SetPropertyValue(string pszDeviceName, out IntPtr key, out IntPtr pv);
    [PreserveSig] int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, uint role);
    [PreserveSig] int SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceName, int bVisible);
}
[ComImport, Guid("bcde0395-e52f-467c-8e3d-c4579291692e")]
class MMDeviceEnumerator {}
[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
class PolicyConfigClient {}
public class AudioHelper {
    [DllImport("ole32")] static extern int CoInitializeEx(IntPtr pvReserved, int dwCoInit);
    static readonly PROPERTYKEY PKEY_FriendlyName = new PROPERTYKEY { fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"), pid = 2 };

    public static string ListCapture() {
        CoInitializeEx(IntPtr.Zero, 2);
        var sb = new StringBuilder();
        IMMDeviceEnumerator en = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        IMMDeviceCollection coll; en.EnumAudioEndpoints(1, 15, out coll);
        int n; coll.GetCount(out n);
        for (int i = 0; i < n; i++) {
            IMMDevice dev; coll.Item(i, out dev);
            string id; dev.GetId(out id);
            sb.AppendLine(id + "||" + GetName(dev));
        }
        return sb.ToString();
    }
    public static string GetDefaultCaptureId() {
        CoInitializeEx(IntPtr.Zero, 2);
        IMMDeviceEnumerator en = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        IMMDevice dev; en.GetDefaultAudioEndpoint(1, 0, out dev);
        string id; dev.GetId(out id);
        return id;
    }
    static string GetName(IMMDevice dev) {
        try {
            IPropertyStore store; dev.OpenPropertyStore(0, out store);
            PROPVARIANT pv = new PROPVARIANT();
            PROPERTYKEY k = PKEY_FriendlyName;
            if (store.GetValue(ref k, out pv) == 0 && pv.vt == 31 && pv.data != IntPtr.Zero)
                return Marshal.PtrToStringUni(pv.data);
        } catch { }
        return "";
    }
    public static string SetDefault(string id, int visible) {
        CoInitializeEx(IntPtr.Zero, 2);
        IPolicyConfig pc = (IPolicyConfig)new PolicyConfigClient();
        if (visible >= 0) pc.SetEndpointVisibility(id, visible);
        pc.SetDefaultEndpoint(id, 0);
        pc.SetDefaultEndpoint(id, 1);
        pc.SetDefaultEndpoint(id, 2);
        return "ok";
    }
}
'@

Add-Type -TypeDefinition $code

$backupFile = Join-Path $env:TEMP "ets_stereo_mix_backup.json"
$cands = @("立体声混音", "Stereo Mix", "立体声混合", "What U Hear", "Wave Out Mix", "循环回放")

function MatchName($n) {
    foreach ($c in $cands) { if ($n -like "*$c*") { return $true } }
    return $false
}

function Exit-Json($ok, $detail) {
    $r = @{ ok = $ok; detail = $detail }
    Write-Host ($r | ConvertTo-Json -Compress)
    exit 0
}

function Exit-Error($detail) {
    Exit-Json $false $detail
}

try {
    if ($Mode -eq "enable") {
        $lines = [AudioHelper]::ListCapture() -split "`n"
        $stereo = $null
        foreach ($l in $lines) {
            if (-not $l.Trim()) { continue }
            $parts = $l.Split('||')
            $id = $parts[0]
            $name = if ($parts.Length -gt 1) { $parts[1] } else { "" }
            if ((MatchName $name) -and $stereo -eq $null) { $stereo = @{ id = $id; name = $name } }
        }
        if ($stereo -eq $null) {
            Exit-Error "未找到立体声混音设备，请先在系统声音设置中启用它（勾选'显示禁用的设备'后右键启用）"
        }
        # 备份当前默认录音设备，便于恢复
        try {
            $oldId = [AudioHelper]::GetDefaultCaptureId()
            @{ id = $oldId; ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() } | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 $backupFile
        } catch { }
        [AudioHelper]::SetDefault($stereo.id, 1) | Out-Null
        Exit-Json $true ("已启用并把 " + $stereo.name + " 设为默认录音设备")
    }
    elseif ($Mode -eq "restore") {
        if (-not (Test-Path $backupFile)) {
            Exit-Error "未找到备份文件，无法恢复（可能本次会话从未启用过立体声混音）"
        }
        $bak = Get-Content -Encoding UTF8 $backupFile | ConvertFrom-Json
        if (-not $bak.id) {
            Exit-Error "备份文件中没有设备 ID"
        }
        [AudioHelper]::SetDefault($bak.id, -1) | Out-Null
        Exit-Json $true ("已恢复默认设备为 " + $bak.id)
    }
    elseif ($Mode -eq "list") {
        $defaultId = $null
        try { $defaultId = [AudioHelper]::GetDefaultCaptureId() } catch { }
        $devices = @()
        foreach ($l in ([AudioHelper]::ListCapture() -split "`n")) {
            if (-not $l.Trim()) { continue }
            $parts = $l.Split('||')
            $devices += [PSCustomObject]@{ Id = $parts[0]; Name = if ($parts.Length -gt 1) { $parts[1] } else { "" }; IsDefault = ($parts[0] -eq $defaultId) }
        }
        Write-Host (@{ default = $defaultId; devices = $devices } | ConvertTo-Json -Depth 3)
    }
    else {
        Exit-Error "未知模式：$Mode（可用 enable / restore / list）"
    }
}
catch {
    Exit-Error $_.Exception.Message
}
