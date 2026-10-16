# Draws the icon used by dev-install.ps1's Start Menu shortcut (PNG/DIB frames, 16-256 px).
# Each size is drawn natively rather than downscaled so small sizes stay crisp.
param([Parameter(Mandatory)][string]$Out)
Add-Type -AssemblyName System.Drawing

New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null
$sizes = 16, 20, 24, 32, 40, 48, 64, 128, 256

function New-RoundedRect([float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = 2 * $r
    $p.AddArc($x, $y, $d, $d, 180, 90)
    $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    $p
}

function Get-Angle([double]$x, [double]$y) { [Math]::Atan2($y, $x) * 180 / [Math]::PI }

# Crescent = circle A minus circle B, built from two arcs so it stays anti-aliased.
function New-Crescent([double]$ax, [double]$ay, [double]$ra, [double]$bx, [double]$by, [double]$rb) {
    $dx = $bx - $ax; $dy = $by - $ay; $d = [Math]::Sqrt($dx * $dx + $dy * $dy)
    $a = ($ra * $ra - $rb * $rb + $d * $d) / (2 * $d); $h = [Math]::Sqrt($ra * $ra - $a * $a)
    $mx = $ax + $a * $dx / $d; $my = $ay + $a * $dy / $d
    $p1 = @(($mx + $h * $dy / $d), ($my - $h * $dx / $d))
    $p2 = @(($mx - $h * $dy / $d), ($my + $h * $dx / $d))

    # Outer arc of A from p1 to p2 on the side away from B.
    $t1 = Get-Angle ($p1[0] - $ax) ($p1[1] - $ay); $t2 = Get-Angle ($p2[0] - $ax) ($p2[1] - $ay)
    $sweepA = (($t2 - $t1) % 360 + 360) % 360
    $mid = ($t1 + $sweepA / 2) * [Math]::PI / 180
    if ([Math]::Cos($mid) * $dx + [Math]::Sin($mid) * $dy -gt 0) { $sweepA -= 360 }
    # Inner arc of B from p2 back to p1, the part lying inside A.
    $u2 = Get-Angle ($p2[0] - $bx) ($p2[1] - $by); $u1 = Get-Angle ($p1[0] - $bx) ($p1[1] - $by)
    $sweepB = (($u1 - $u2) % 360 + 360) % 360
    $mid = ($u2 + $sweepB / 2) * [Math]::PI / 180
    if ([Math]::Cos($mid) * $dx + [Math]::Sin($mid) * $dy -gt 0) { $sweepB -= 360 }

    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $p.AddArc([float]($ax - $ra), [float]($ay - $ra), [float](2 * $ra), [float](2 * $ra), [float]$t1, [float]$sweepA)
    $p.AddArc([float]($bx - $rb), [float]($by - $rb), [float](2 * $rb), [float](2 * $rb), [float]$u2, [float]$sweepB)
    $p.CloseFigure()
    $p
}

function Add-Star($g, $brush, [float]$cx, [float]$cy, [float]$r) {
    # Four-point sparkle.
    $k = $r * 0.28
    $pts = [System.Drawing.PointF[]]@(
        (New-Object System.Drawing.PointF $cx, ($cy - $r)), (New-Object System.Drawing.PointF ($cx + $k), ($cy - $k)),
        (New-Object System.Drawing.PointF ($cx + $r), $cy), (New-Object System.Drawing.PointF ($cx + $k), ($cy + $k)),
        (New-Object System.Drawing.PointF $cx, ($cy + $r)), (New-Object System.Drawing.PointF ($cx - $k), ($cy + $k)),
        (New-Object System.Drawing.PointF ($cx - $r), $cy), (New-Object System.Drawing.PointF ($cx - $k), ($cy - $k)))
    $g.FillPolygon($brush, $pts)
}

function New-Frame([int]$s) {
    $bmp = New-Object System.Drawing.Bitmap $s, $s, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.PixelOffsetMode = 'HighQuality'
    $g.Clear([System.Drawing.Color]::Transparent)

    # Rounded tile with a diagonal night-sky gradient: deep indigo -> teal.
    $pad = [Math]::Max(0.5, $s * 0.03)
    $tile = New-RoundedRect $pad $pad ($s - 2 * $pad) ($s - 2 * $pad) ($s * 0.22)
    $grad = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.PointF 0, 0), (New-Object System.Drawing.PointF $s, $s),
        [System.Drawing.Color]::FromArgb(255, 49, 46, 129), [System.Drawing.Color]::FromArgb(255, 14, 116, 144))
    $g.FillPath($grad, $tile)

    # Warm crescent moon, opening to the upper right.
    $moon = New-Crescent ($s * 0.46) ($s * 0.54) ($s * 0.31) ($s * 0.60) ($s * 0.43) ($s * 0.26)
    $g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 254, 243, 199))), $moon)

    # Two stars in the crescent's opening (skipped where they would be mush).
    if ($s -ge 24) {
        $star = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
        Add-Star $g $star ($s * 0.73) ($s * 0.30) ($s * 0.10)
        if ($s -ge 40) { Add-Star $g $star ($s * 0.78) ($s * 0.58) ($s * 0.055) }
    }
    $g.Dispose()

    $ms = New-Object System.IO.MemoryStream
    if ($s -ge 256) {
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    } else {
        # Small frames as 32-bit DIBs, which every icon consumer (incl. GDI+) can read.
        $data = $bmp.LockBits((New-Object System.Drawing.Rectangle 0, 0, $s, $s), 'ReadOnly',
            [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $pixels = New-Object byte[] ($data.Stride * $s)
        [System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $pixels, 0, $pixels.Length)
        $bmp.UnlockBits($data)
        $bw = New-Object System.IO.BinaryWriter $ms
        $bw.Write([UInt32]40); $bw.Write([Int32]$s); $bw.Write([Int32](2 * $s))  # height covers XOR + AND
        $bw.Write([UInt16]1); $bw.Write([UInt16]32); $bw.Write([UInt32]0)
        $bw.Write([UInt32]0); $bw.Write([Int32]0); $bw.Write([Int32]0); $bw.Write([UInt32]0); $bw.Write([UInt32]0)
        for ($row = $s - 1; $row -ge 0; $row--) { $bw.Write($pixels, $row * $data.Stride, 4 * $s) }  # bottom-up BGRA
        $maskStride = [int][Math]::Floor(($s + 31) / 32) * 4
        $bw.Write((New-Object byte[] ($maskStride * $s)))  # empty AND mask; alpha does the work
        $bw.Flush()
    }
    $bmp.Dispose()
    , $ms.ToArray()
}

$frames = foreach ($s in $sizes) { , (New-Frame $s) }

# ICO container: ICONDIR + ICONDIRENTRY[] + payloads.
$fs = [System.IO.File]::Create($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out))
$w = New-Object System.IO.BinaryWriter $fs
$w.Write([UInt16]0); $w.Write([UInt16]1); $w.Write([UInt16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $dim = if ($sizes[$i] -ge 256) { 0 } else { $sizes[$i] }
    $w.Write([byte]$dim); $w.Write([byte]$dim); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([UInt16]1); $w.Write([UInt16]32)
    $w.Write([UInt32]$frames[$i].Length); $w.Write([UInt32]$offset)
    $offset += $frames[$i].Length
}
foreach ($f in $frames) { $w.Write($f) }
$w.Close()
"Wrote $Out"
