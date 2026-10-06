// Log.cs —— 统一的诊断日志出口。
//
// 为什么单独放一个类：AppController 和 SettingsForm 都要写日志，
// 而"怎么写"这件事有个必须统一的细节 —— 不能走 Console.Error，
// 它用的是控制台的 OEM 代码页（本机 GBK），中文会被编成乱码而且不可逆还原
// （实测重定向到文件后拿到一堆 EF BF BD）。所以这里直接把 UTF-8 字节写进
// 标准错误流，绕过那个 TextWriter。
using System;
using System.Text;

namespace ScreenWatermark
{
    internal static class Log
    {
        private static readonly object Gate = new object();

        public static void Warn(string line)
        {
            Write(line);
        }

        public static void Info(string line)
        {
            Write(line);
        }

        private static void Write(string line)
        {
            try
            {
                byte[] bytes = new UTF8Encoding(false).GetBytes("ScreenWatermark: " + line + "\r\n");
                lock (Gate)
                {
                    System.IO.Stream st = Console.OpenStandardError();
                    st.Write(bytes, 0, bytes.Length);
                    st.Flush();
                }
            }
            catch (Exception)
            {
                // 双击启动的 winexe 没有 stderr，这不是错误，忽略即可。
            }
        }
    }
}
