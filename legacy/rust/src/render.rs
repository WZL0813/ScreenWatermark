// 水印渲染：算出平铺参数，用 GDI+ 的 flat API 画进 32bpp PARGB 的 DIB。
// 这里只负责"画出一张图"，贴到屏幕上由 overlay.rs 用 UpdateLayeredWindow 完成。

use crate::config::Config;
use crate::ffi::*;
use crate::util::{expand_template, from_wide, to_wide};
use std::ffi::c_void;

/// 单次重绘的单元数上限。极端角度/间距下网格会爆炸，宁可少画也不能卡死。
pub const MAX_CELLS: i64 = 20000;

/// GDI+ 全局初始化一次，返回 token（退出时要用它关掉）。
pub fn gdiplus_startup() -> Result<ULONG_PTR, String> {
    let input = GdiplusStartupInput {
        GdiplusVersion: 1,
        DebugEventCallback: std::ptr::null_mut(),
        SuppressBackgroundThread: 0,
        SuppressExternalCodecs: 0,
    };
    let mut token: ULONG_PTR = 0;
    let mut output: *mut c_void = std::ptr::null_mut();
    let st = unsafe { GdiplusStartup(&mut token, &input, &mut output) };
    if st != GP_OK {
        return Err(format!("GdiplusStartup 失败，状态码 {}", st));
    }
    Ok(token)
}

pub fn gdiplus_shutdown(token: ULONG_PTR) {
    if token != 0 {
        unsafe { GdiplusShutdown(token) };
    }
}

/// 一张画好的位图：DIB 像素 + GDI+ 包装 + 内存 DC。
/// overlay 拿它做 UpdateLayeredWindow，用完必须 dispose()，否则内存一路上涨。
pub struct RenderedBitmap {
    pub width: i32,
    pub height: i32,
    pub mem_dc: HDC,
    pub hbmp: HBITMAP,
    pub bits: *mut u8,
    pub gp_bitmap: GpBitmap,
    pub gp_graphics: GpGraphics,
}

// 这些句柄本来就是进程内 GDI 对象，跨线程只要不并发调用就安全。
unsafe impl Send for RenderedBitmap {}

impl RenderedBitmap {
    /// 按 §10 建 32bpp top-down DIB，再用 GDI+ 包住同一块像素。
    pub fn create(width: i32, height: i32) -> Result<RenderedBitmap, String> {
        if width <= 0 || height <= 0 {
            return Err(format!("非法位图尺寸 {}x{}", width, height));
        }
        unsafe {
            let screen_dc = GetDC(std::ptr::null_mut());
            if screen_dc.is_null() {
                return Err("GetDC(NULL) 失败".to_string());
            }
            let mem_dc = CreateCompatibleDC(screen_dc);
            if mem_dc.is_null() {
                ReleaseDC(std::ptr::null_mut(), screen_dc);
                return Err("CreateCompatibleDC 失败".to_string());
            }

            // 负高度 = top-down，GDI+ 的 stride 和我们的想象一致，省得翻转。
            let mut bmi = BITMAPINFO {
                bmiHeader: BITMAPINFOHEADER {
                    biSize: core::mem::size_of::<BITMAPINFOHEADER>() as DWORD,
                    biWidth: width,
                    biHeight: -height,
                    biPlanes: 1,
                    biBitCount: 32,
                    biCompression: BI_RGB,
                    biSizeImage: (width as u32) * (height as u32) * 4,
                    biXPelsPerMeter: 0,
                    biYPelsPerMeter: 0,
                    biClrUsed: 0,
                    biClrImportant: 0,
                },
                bmiColors: [0; 3],
            };
            let mut bits: *mut c_void = std::ptr::null_mut();
            let hbmp = CreateDIBSection(
                screen_dc,
                &mut bmi,
                DIB_RGB_COLORS,
                &mut bits,
                std::ptr::null_mut(),
                0,
            );
            ReleaseDC(std::ptr::null_mut(), screen_dc);
            if hbmp.is_null() || bits.is_null() {
                DeleteDC(mem_dc);
                return Err("CreateDIBSection 失败".to_string());
            }
            let old = SelectObject(mem_dc, hbmp as HGDIOBJ);
            // old 可能是 HGDI_ERROR，但不影响后续绘制，这里不做断言。

            // 预乘 alpha：先全清零，之后所有绘制都由 GDI+ 负责预乘。
            std::ptr::write_bytes(bits as *mut u8, 0, (width as usize) * (height as usize) * 4);

            let stride = width * 4;
            let mut gp_bitmap: GpBitmap = std::ptr::null_mut();
            let st = GdipCreateBitmapFromScan0(
                width,
                height,
                stride,
                PixelFormat32bppPARGB,
                bits as *mut u8,
                &mut gp_bitmap,
            );
            if st != GP_OK || gp_bitmap.is_null() {
                SelectObject(mem_dc, old);
                DeleteObject(hbmp as HGDIOBJ);
                DeleteDC(mem_dc);
                return Err(format!("GdipCreateBitmapFromScan0 失败，状态码 {}", st));
            }
            let mut gp_graphics: GpGraphics = std::ptr::null_mut();
            let st = GdipGetImageGraphicsContext(gp_bitmap, &mut gp_graphics);
            if st != GP_OK || gp_graphics.is_null() {
                GdipDisposeImage(gp_bitmap);
                SelectObject(mem_dc, old);
                DeleteObject(hbmp as HGDIOBJ);
                DeleteDC(mem_dc);
                return Err(format!("GdipGetImageGraphicsContext 失败，状态码 {}", st));
            }
            Ok(RenderedBitmap {
                width,
                height,
                mem_dc,
                hbmp,
                bits: bits as *mut u8,
                gp_bitmap,
                gp_graphics,
            })
        }
    }

    /// 资源释放顺序要求：GDI+ 对象先于 DIB 和 DC。
    pub fn dispose(self) {
        unsafe {
            if !self.gp_graphics.is_null() {
                GdipDeleteGraphics(self.gp_graphics);
            }
            if !self.gp_bitmap.is_null() {
                GdipDisposeImage(self.gp_bitmap);
            }
            if !self.mem_dc.is_null() {
                SelectObject(self.mem_dc, std::ptr::null_mut());
                DeleteDC(self.mem_dc);
            }
            if !self.hbmp.is_null() {
                DeleteObject(self.hbmp as HGDIOBJ);
            }
        }
    }
}

/// 本次平铺的几何参数。抽出来是为了让日志/自检能看到"到底铺了多少个单元"。
#[derive(Debug, Clone, Copy)]
pub struct TilePlan {
    pub cell_w: i32,
    pub cell_h: i32,
    pub text_w: i32,
    pub line_h: i32,
    pub cols: i64,
    pub rows: i64,
    pub cells: i64,
    pub clamped: bool,
}

impl TilePlan {
    /// 按 §6 的公式算单元尺寸和行列数。
    pub fn compute(
        width: i32,
        height: i32,
        text_w: i32,
        line_h: i32,
        gap_x: i32,
        gap_y: i32,
        line_spacing: f64,
    ) -> TilePlan {
        let cell_w = (text_w + gap_x).max(4);
        let cell_h = ((line_h as f64 * line_spacing) as i32 + gap_y).max(4);
        let cols = ((width as i64 + 2 * cell_w as i64) / cell_w as i64 + 1).max(1);
        let rows = ((height as i64 + 2 * cell_h as i64) / cell_h as i64 + 1).max(1);
        let mut cells = cols * rows;
        let mut clamped = false;
        if cells > MAX_CELLS {
            clamped = true;
            cells = MAX_CELLS;
        }
        TilePlan {
            cell_w,
            cell_h,
            text_w,
            line_h,
            cols,
            rows,
            cells,
            clamped,
        }
    }
}

/// 把一个 GDI+ 图形上下文配置成"抗锯齿 + 不换行 + 左对齐"。
/// 设置面板探测字体时不需要，所以单独一个函数，不塞进 render_to。
fn make_string_format() -> Result<GpStringFormat, String> {
    unsafe {
        let mut fmt: GpStringFormat = std::ptr::null_mut();
        let st = GdipCreateStringFormat(0, 0, &mut fmt);
        if st != GP_OK || fmt.is_null() {
            return Err(format!("GdipCreateStringFormat 失败，状态码 {}", st));
        }
        // 单元宽度按单行文字量出来，所以必须禁止自动换行，否则长文本会被折行。
        GdipSetStringFormatFlags(fmt, StringFormatFlagsNoWrap);
        GdipSetStringFormatAlign(fmt, StringAlignmentNear);
        GdipSetStringFormatLineAlign(fmt, StringAlignmentNear);
        Ok(fmt)
    }
}

/// 画一屏水印。返回 (位图, 平铺计划)；位图归调用者释放。
pub fn render_to(
    width: i32,
    height: i32,
    cfg: &Config,
    dpi: u32,
) -> Result<(RenderedBitmap, TilePlan), String> {
    use std::time::Instant;
    let t0 = Instant::now();

    let bmp = RenderedBitmap::create(width, height)?;

    // 模板变量在渲染那一刻求值；时间跳变由外层定时器触发重画。
    let text = expand_template(cfg, &cfg.text);
    let lines: Vec<String> = text.split('\n').map(|s| s.to_string()).collect();

    unsafe {
        let g = bmp.gp_graphics;
        // 抗锯齿，规格 §6 明确要求。
        GdipSetSmoothingMode(g, SmoothingModeAntiAlias);
        // ClearType 在预乘 alpha 的位图上会出彩边，用灰度抗锯齿更干净。
        GdipSetTextRenderingHint(g, TextRenderingHintAntiAliasGridFit);

        // 字体族：配置里的优先，找不到就回退，再不行交给 GDI+ 默认族。
        let mut family: GpFontFamily = std::ptr::null_mut();
        let mut st = GdipCreateFontFamilyFromName(
            to_wide(&cfg.font_family).as_ptr(),
            std::ptr::null_mut(),
            &mut family,
        );
        if st != GP_OK || family.is_null() {
            family = std::ptr::null_mut();
            for cand in ["Microsoft YaHei", "Segoe UI", "SimSun", "Arial"] {
                let w = to_wide(cand);
                st = GdipCreateFontFamilyFromName(w.as_ptr(), std::ptr::null_mut(), &mut family);
                if st == GP_OK && !family.is_null() {
                    break;
                }
                family = std::ptr::null_mut();
            }
        }

        let mut style = FontStyleRegular;
        if cfg.bold {
            style |= FontStyleBold;
        }
        if cfg.italic {
            style |= FontStyleItalic;
        }

        // §2 的 font_size 是磅值，GDI+ 的 UnitPoint 会按 DPI 自己换算成像素。
        let mut font: GpFont = std::ptr::null_mut();
        st = GdipCreateFont(family, cfg.font_size as f32, style, UnitPoint, &mut font);
        if st != GP_OK || font.is_null() {
            if !family.is_null() {
                GdipDeleteFontFamily(family);
            }
            bmp.dispose();
            return Err(format!("GdipCreateFont 失败，状态码 {}", st));
        }

        let dpi_f = if dpi >= 48 { dpi as f32 } else { 96.0 };
        let mut line_h_f: f32 = 0.0;
        GdipGetFontHeightGivenDPI(font, dpi_f, &mut line_h_f);
        if !(line_h_f.is_finite()) || line_h_f < 1.0 {
            line_h_f = (cfg.font_size as f32 * dpi_f / 72.0).max(8.0);
        }
        let line_h = line_h_f.ceil() as i32;

        let fmt = match make_string_format() {
            Ok(f) => f,
            Err(e) => {
                GdipDeleteFont(font);
                if !family.is_null() {
                    GdipDeleteFontFamily(family);
                }
                bmp.dispose();
                return Err(e);
            }
        };

        // 量文字宽度：逐行量取最大值。layoutRect 给足宽高，避免 GDI+ 提前折行。
        let measure_probe = RectF {
            X: 0.0,
            Y: 0.0,
            Width: 1.0e6,
            Height: (line_h as f32) * 4.0 + 64.0,
        };
        let mut text_w: i32 = 1;
        for line in &lines {
            let wline = to_wide(line);
            let mut bb = RectF::default();
            let st = GdipMeasureString(
                g,
                wline.as_ptr(),
                line.chars().count() as i32,
                font,
                &measure_probe,
                fmt,
                &mut bb,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            );
            if st == GP_OK {
                let w = bb.Width.ceil() as i32 + 2;
                if w > text_w {
                    text_w = w;
                }
            }
        }
        // 纯空白文本量出来可能很小，给个下限，否则单元会挤成一条线。
        if text_w < 4 {
            text_w = 4;
        }

        let plan = TilePlan::compute(
            width,
            height,
            text_w,
            line_h,
            cfg.gap_x,
            cfg.gap_y,
            cfg.line_spacing,
        );

        // 颜色 = 配置色 × opacity，alpha 是唯一的不透明来源。
        let (r, gc, b) = crate::util::parse_color(&cfg.color);
        let a = (cfg.opacity.clamp(0.0, 1.0) * 255.0).round() as u32;
        let argb: ARGB = (a << 24) | ((r as u32) << 16) | ((gc as u32) << 8) | (b as u32);
        let mut brush: GpBrush = std::ptr::null_mut();
        st = GdipCreateSolidFill(argb, &mut brush);
        if st != GP_OK || brush.is_null() {
            GdipDeleteStringFormat(fmt);
            GdipDeleteFont(font);
            if !family.is_null() {
                GdipDeleteFontFamily(family);
            }
            bmp.dispose();
            return Err(format!("GdipCreateSolidFill 失败，状态码 {}", st));
        }

        // 每个单元给文字留的绘制矩形：旋转后要能装下整段文字。
        let rad = (cfg.angle as f64).to_radians().abs();
        let (sin_a, cos_a) = (rad.sin(), rad.cos());
        let pad_x = ((text_w as f64 * cos_a + line_h as f64 * sin_a).ceil() as i32 + 8).max(16);
        let pad_y = ((text_w as f64 * sin_a + line_h as f64 * cos_a).ceil() as i32 + 8).max(16);
        let draw_rect = RectF {
            X: 0.0,
            Y: 0.0,
            Width: pad_x as f32,
            Height: pad_y as f32,
        };

        // 预乘 alpha 的 DIB 上，GDI+ 的合成按 src-over，不透明区域不会互相加深。
        let mut drawn: i64 = 0;
        let mut row: i64 = 0;
        let mut y = -(plan.cell_h as i64);
        'outer: while y < height as i64 + plan.cell_h as i64 {
            // phase_offset：奇数行右移半格，看起来不像死板的网格。
            let phase = if cfg.phase_offset && row % 2 == 1 {
                plan.cell_w as f64 / 2.0
            } else {
                0.0
            };
            let mut x = -(plan.cell_w as i64);
            while x < width as i64 + plan.cell_w as i64 {
                let dx = x as f64 + phase;
                let dy = y as f64;
                // 先平移再旋转（append 顺序 = 先平移后旋转），最后绕单元原点左对齐画字。
                GdipTranslateWorldTransform(g, dx as f32, dy as f32, MatrixOrderPrepend);
                GdipRotateWorldTransform(g, -(cfg.angle as f32), MatrixOrderPrepend);
                for (li, line) in lines.iter().enumerate() {
                    if line.is_empty() {
                        continue;
                    }
                    let wline = to_wide(line);
                    let mut rect = draw_rect;
                    rect.Y = (li as f32) * line_h as f32 * cfg.line_spacing as f32;
                    GdipDrawString(
                        g,
                        wline.as_ptr(),
                        line.chars().count() as i32,
                        font,
                        &rect,
                        fmt,
                        brush,
                    );
                }
                GdipResetWorldTransform(g);
                drawn += 1;
                if drawn >= MAX_CELLS {
                    break 'outer;
                }
                x += plan.cell_w as i64;
            }
            y += plan.cell_h as i64;
            row += 1;
        }
        GdipFlush(g, FlushIntentionSync);

        GdipDeleteBrush(brush);
        GdipDeleteStringFormat(fmt);
        GdipDeleteFont(font);
        if !family.is_null() {
            GdipDeleteFontFamily(family);
        }

        // 极端参数下单元数可能超过上限，这里如实标注，调用方可据此提示。
        let mut final_plan = plan;
        final_plan.cells = drawn;
        let _ = t0;

        Ok((bmp, final_plan))
    }
}

/// 从 DIB 像素里数一下非零 alpha 的比例，用于自检和日志。
pub fn coverage(bmp: &RenderedBitmap) -> f64 {
    if bmp.bits.is_null() || bmp.width <= 0 || bmp.height <= 0 {
        return 0.0;
    }
    let total = (bmp.width as usize) * (bmp.height as usize);
    let mut nonzero = 0usize;
    unsafe {
        let p = bmp.bits;
        for i in 0..total {
            // BGRA 顺序，alpha 在第 4 字节；预乘后非零 alpha 即"有内容"。
            if *p.add(i * 4 + 3) > 8 {
                nonzero += 1;
            }
        }
    }
    nonzero as f64 / total as f64
}

/// 设置面板用：把候选字体名做成下拉列表内容。
#[allow(dead_code)]
pub fn font_display_name(name: &str) -> String {
    name.to_string()
}

/// 给日志用：描述这次重绘的规模。
pub fn describe(width: i32, height: i32, plan: &TilePlan, ms: f64) -> String {
    format!(
        "渲染 {}x{}：单元 {}×{}={} (文字宽 {} 行高 {} 单元 {}×{})，耗时 {:.1}ms{}",
        width,
        height,
        plan.cols,
        plan.rows,
        plan.cells,
        plan.text_w,
        plan.line_h,
        plan.cell_w,
        plan.cell_h,
        ms,
        if plan.clamped { "（已达上限）" } else { "" }
    )
}

/// 只是为了让 from_wide 在这个模块也被用到（托盘/自检会借它）。
#[allow(dead_code)]
pub fn wide_str_for_debug(s: &str) -> String {
    from_wide(&to_wide(s))
}
