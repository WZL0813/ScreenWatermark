// 链接参数都在这里定：gnu 目标下 rustc 不会把 windows_subsystem 属性
// 翻译成 -mwindows，默认走 console 子系统，双击 exe 会闪一个黑框。
//
// -static-libgcc / -static-libstdc++：与 C++ 版保持一致，不依赖 MinGW 的
// 运行库 DLL，exe 拷到别的机器上也能跑。Rust 自己的 crt 是静态的，
// 再加上这两个就把 gcc 运行库也钉死了。
fn main() {
    let target = std::env::var("TARGET").unwrap_or_default();
    if target.contains("windows") {
        println!("cargo:rustc-link-arg=-mwindows");
        if target.contains("gnu") {
            println!("cargo:rustc-link-arg=-static-libgcc");
            println!("cargo:rustc-link-arg=-static-libstdc++");
        }
    }
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=res/app.rc");
    println!("cargo:rerun-if-changed=res/app.manifest");
}
