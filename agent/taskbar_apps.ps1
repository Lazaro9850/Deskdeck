# Lista os apps fixados na barra de tarefas do Windows com icone PNG (base64).
# Saida: JSON [{file, name, target, args, png}] em stdout (UTF-8).
param([int]$Size = 96)
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Drawing;
using System.Drawing.Imaging;
public static class PainelShellIcon {
    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItemImageFactory { [PreserveSig] int GetImage(SIZE size, int flags, out IntPtr phbm); }
    [StructLayout(LayoutKind.Sequential)] struct SIZE { public int cx, cy; }
    [StructLayout(LayoutKind.Sequential)] struct BITMAP { public int bmType, bmWidth, bmHeight, bmWidthBytes; public short bmPlanes, bmBitsPixel; public IntPtr bmBits; }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out IShellItemImageFactory ppv);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);
    [DllImport("gdi32.dll")] static extern int GetObject(IntPtr h, int c, ref BITMAP bm);

    public static string Png(string path, int size) {
        Guid g = new Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b");
        IShellItemImageFactory f;
        SHCreateItemFromParsingName(path, IntPtr.Zero, ref g, out f);
        IntPtr hb;
        SIZE sz; sz.cx = size; sz.cy = size;
        if (f.GetImage(sz, 0x4 /* SIIGBF_ICONONLY */, out hb) != 0) return null;
        try {
            BITMAP bm = new BITMAP();
            GetObject(hb, Marshal.SizeOf(typeof(BITMAP)), ref bm);
            Bitmap bmp;
            if (bm.bmBitsPixel == 32 && bm.bmBits != IntPtr.Zero) {
                int w = bm.bmWidth, h = Math.Abs(bm.bmHeight);
                bmp = new Bitmap(w, h, PixelFormat.Format32bppPArgb);
                BitmapData d = bmp.LockBits(new Rectangle(0, 0, w, h), ImageLockMode.WriteOnly, PixelFormat.Format32bppPArgb);
                byte[] row = new byte[bm.bmWidthBytes];
                // DIB do GDI vem de baixo para cima: a ultima linha da memoria e o topo da imagem.
                for (int y = 0; y < h; y++) {
                    Marshal.Copy(new IntPtr(bm.bmBits.ToInt64() + (long)(h - 1 - y) * bm.bmWidthBytes), row, 0, row.Length);
                    Marshal.Copy(row, 0, new IntPtr(d.Scan0.ToInt64() + (long)y * d.Stride), Math.Min(row.Length, d.Stride));
                }
                bmp.UnlockBits(d);
            } else {
                bmp = Image.FromHbitmap(hb);
            }
            using (var ms = new System.IO.MemoryStream()) { bmp.Save(ms, ImageFormat.Png); return Convert.ToBase64String(ms.ToArray()); }
        } finally { DeleteObject(hb); }
    }
}
"@
$dir = "$env:APPDATA\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"
$ws = New-Object -ComObject WScript.Shell
$out = @()
foreach ($f in Get-ChildItem $dir -Filter *.lnk) {
    $s = $ws.CreateShortcut($f.FullName)
    $png = $null
    try { $png = [PainelShellIcon]::Png($f.FullName, $Size) } catch {}
    $out += [pscustomobject]@{ file = $f.Name; name = $f.BaseName; path = $f.FullName; target = $s.TargetPath; args = $s.Arguments; png = $png }
}
# Logotipo "sem fundo" (altform-unplated) do pacote, no maior tamanho disponivel.
function Get-StoreLogo([string]$aumid, [int]$size) {
    Add-Type -AssemblyName System.Drawing
    $fam = ($aumid -split '!')[0]
    $pkg = Get-AppxPackage | Where-Object { $_.PackageFamilyName -eq $fam } | Select-Object -First 1
    if (-not $pkg) { return $null }
    [xml]$man = Get-Content (Join-Path $pkg.InstallLocation 'AppxManifest.xml') -Raw
    $app = @($man.Package.Applications.Application) | Where-Object { $_.Id -eq ($aumid -split '!')[1] } | Select-Object -First 1
    $logo = $app.VisualElements.Square44x44Logo
    if (-not $logo) { return $null }
    $dir = Join-Path $pkg.InstallLocation (Split-Path $logo)
    $base = [IO.Path]::GetFileNameWithoutExtension($logo)
    $files = Get-ChildItem $dir -Filter "$base*.png" -ErrorAction SilentlyContinue
    $best = $files | Where-Object { $_.Name -match 'unplated' } | Sort-Object Length -Descending | Select-Object -First 1
    if (-not $best) { $best = $files | Where-Object { $_.Name -match 'targetsize' } | Sort-Object Length -Descending | Select-Object -First 1 }
    if (-not $best) { return $null }
    $src = [Drawing.Image]::FromFile($best.FullName)
    $bmp = New-Object Drawing.Bitmap $size, $size
    $g = [Drawing.Graphics]::FromImage($bmp); $g.InterpolationMode = 'HighQualityBicubic'
    $g.DrawImage($src, 0, 0, $size, $size); $g.Dispose(); $src.Dispose()
    $ms = New-Object IO.MemoryStream; $bmp.Save($ms, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    return [Convert]::ToBase64String($ms.ToArray())
}

# Apps da Microsoft Store / MSIX (WhatsApp, Claude...) nao tem .lnk: aparecem so no
# registro Taskband pelo AppUserModelID ("Pacote_hash!App").
try {
    $blob = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Taskband').Favorites
    $txt = [Text.Encoding]::Unicode.GetString($blob)
    $start = @{}; Get-StartApps | ForEach-Object { $start[$_.AppID] = $_.Name }
    $seen = @{}
    foreach ($m in [regex]::Matches($txt, '[A-Za-z0-9._-]+_[a-z0-9]{8,}![A-Za-z0-9._-]+')) {
        $id = $m.Value
        if ($seen[$id]) { continue }; $seen[$id] = 1
        $name = $start[$id]; if (-not $name) { $name = ($id -split '!')[0] -replace '_.*$', '' -replace '^[0-9A-F]+\.', '' }
        $path = "shell:AppsFolder\$id"
        $png = $null
        try { $png = Get-StoreLogo $id $Size } catch {}
        if (-not $png) { try { $png = [PainelShellIcon]::Png($path, $Size) } catch {} }
        $out += [pscustomobject]@{ file = $id; name = $name; path = $path; target = ''; args = ''; aumid = $id; png = $png }
    }
} catch {}
ConvertTo-Json -InputObject @($out) -Compress
