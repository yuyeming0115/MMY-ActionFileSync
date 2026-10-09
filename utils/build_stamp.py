"""输出构建标识：APP_VERSION 与 yyyyMMdd_HHMMSS 时间戳，空格分隔。

供 build_exe.bat 以 `python -m utils.build_stamp` 调用并捕获输出；
独立成脚本是为了避开 bat 内嵌 python -c 时的引号/百分号转义问题。
"""

from datetime import datetime

from utils.app_info import APP_VERSION


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(APP_VERSION, stamp)


if __name__ == "__main__":
    main()
