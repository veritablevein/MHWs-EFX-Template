import os
import subprocess
import sys
import re
import glob
import threading
import datetime # 用于生成带时间戳的文件名
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.parse

# --- 帮助函数：获取用户输入 ---
def get_user_input(prompt, default=None, input_type=str, choices=None):
    """帮助函数，用于获取用户输入，支持默认值、类型转换和选项限制。"""
    while True:
        if default is not None:
            user_val_str = input(f"{prompt} [{default}]: ").strip()
            if not user_val_str:
                if input_type == bool and isinstance(default, str):
                    return default.lower() in ['yes', 'y', 'true', 't', '1']
                return default
        else:
            user_val_str = input(f"{prompt}: ").strip()
            if not user_val_str and input_type != bool:
                print("输入不能为空。")
                continue
        try:
            if input_type == bool:
                if user_val_str.lower() in ['yes', 'y', 'true', 't', '1']: val = True
                elif user_val_str.lower() in ['no', 'n', 'false', 'f', '0']: val = False
                else:
                    if default is not None and isinstance(default, bool):
                        print(f"无法识别的布尔输入 '{user_val_str}'。将使用默认值: {default}")
                        return default
                    raise ValueError("无效的布尔输入。请输入 yes/no, true/false, y/n, t/f, 1/0。")
            elif input_type == int :
                val = int(user_val_str)
                if val <= 0 and "线程数" in prompt : # 确保只针对线程数做这个检查
                    raise ValueError("线程数必须为正整数。")
            else: val = input_type(user_val_str)

            if choices and val not in choices:
                print(f"无效的选择。请从以下选项中选择: {', '.join(map(str, choices))}")
                continue
            return val
        except ValueError as e:
            print(f"输入无效: {e}。请重试。")

# --- 帮助函数：从最新的OK文件列表加载路径 ---
def load_previously_ok_files_from_txt(log_dir: Path) -> set:
    """从日志目录中最新的 'ok_files_*.txt' 加载先前标记为OK的文件绝对路径集合。"""
    previously_ok_files = set()
    ok_file_pattern = "ok_files_*.txt"
    
    if not log_dir.exists(): # 如果日志目录本身就不存在
        print(f"提示：日志目录 '{log_dir}' 不存在，无法加载先前的OK文件列表。将处理所有匹配文件。")
        return previously_ok_files

    ok_files = sorted(log_dir.glob(ok_file_pattern), reverse=True) 
    
    if not ok_files:
        print(f"提示：在 '{log_dir}' 未找到先前的OK文件列表 (如 {ok_file_pattern})，将处理所有匹配文件。")
        return previously_ok_files

    latest_ok_file = ok_files[0]
    print(f"正在读取最新的OK文件列表: {latest_ok_file}")
    try:
        with open(latest_ok_file, "r", encoding="utf-8") as f:
            for line in f:
                path_str = line.strip()
                if path_str:
                    previously_ok_files.add(Path(path_str).resolve())
    except Exception as e:
        print(f"警告：读取或解析OK文件列表 '{latest_ok_file}' 时出错: {e}。将处理所有匹配文件。")
        previously_ok_files.clear()

    if previously_ok_files:
        print(f"从 '{latest_ok_file}' 中识别出 {len(previously_ok_files)} 个已OK的文件。")
    return previously_ok_files


# --- 核心处理函数：使用010 Editor处理单个文件 ---
def process_file_with_editor(file_path: Path, editor_exe: Path, template_file: Path, use_noui: bool, use_exit_param: bool, timeout_seconds: int, base_data_dir: Path):
    """
    使用010 Editor处理单个文件。
    返回一个包含处理结果的字典。
    """
    file_path_abs = file_path.resolve() # 确保 file_path 是绝对路径
    filename_only = file_path_abs.name

    # 计算相对路径 (相对于 base_data_dir)
    try:
        # 确保 base_data_dir 也是绝对路径以进行可靠比较
        relative_p_str = str(file_path_abs.relative_to(base_data_dir.resolve()))
    except ValueError:
        # 如果不是子路径（理论上不应发生，除非文件列表构建逻辑有误或 base_data_dir 被错误传递）
        # 则回退到仅使用文件名，或者可以考虑使用路径的最后几部分
        relative_p_str = file_path_abs.name 
        print(f"警告: 文件 '{file_path_abs}' 不在基础数据目录 '{base_data_dir.resolve()}' 的子路径中。相对路径将使用文件名。")


    command = [
        str(editor_exe),
        str(file_path_abs),
        f"-template:{template_file}",
        "-readonly",
        "-nowarnings"
    ]
    if use_noui:
        command.append("-noui")
    if use_exit_param:
        command.append("-exit")

    result = {
        "path": str(file_path_abs),
        "filename": filename_only,
        "relative_path": relative_p_str, # 使用新计算的相对路径
        "status": "ERROR",
        "message": "",
        "stdout": "",
        "stderr": ""
    }
    
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_seconds
        )

        result["stdout"] = process.stdout.strip() if process.stdout else ""
        result["stderr"] = process.stderr.strip() if process.stderr else ""
        stdout_lower = result["stdout"].lower()
        stderr_lower = result["stderr"].lower()

        has_error_keywords = (
            "error" in stdout_lower or "failed" in stdout_lower or "错误" in stdout_lower or
            "error" in stderr_lower or "failed" in stderr_lower or "错误" in stderr_lower or
            "assert" in stderr_lower
        )

        if process.returncode == 0 and not has_error_keywords:
            result["status"] = "OK"
            result["message"] = "处理成功。"
        elif process.returncode == 0 and has_error_keywords:
            result["status"] = "POTENTIAL ERROR"
            result["message"] = f"返回码为0，但在输出中找到错误关键词。请检查输出。"
        else:
            result["status"] = "ERROR"
            result["message"] = f"返回码: {process.returncode}。请检查输出。"

    except subprocess.TimeoutExpired:
        result["status"] = "ERROR"
        result["message"] = f"处理超时（{timeout_seconds}秒）。"
    except FileNotFoundError: # 主要指 editor_exe
        result["status"] = "ERROR"
        result["message"] = f"编辑器可执行文件未找到: {editor_exe}"
    except Exception as e:
        result["status"] = "ERROR"
        result["message"] = f"处理文件 '{file_path_abs.name}' 时发生未知异常: {str(e)}"
    return result


# --- 主验证函数 ---
def validate_templates():
    print("--- 010 Editor 模板批量验证器 (多日志版 v2) ---")

    # --- 默认配置 ---
    # !!重要!! 请根据您的环境修改以下默认路径
    default_editor_exe = r"D:\Software\Code\Hex\010 Editor\010Editor.exe" # 示例路径
    default_template_file = r"D:\Software\Code\Hex\010 Editor\Template\RE4-EFX-Template-main\RE_Engine_EFX.bt" # 示例路径
    default_test_data_dir = r"D:\Software\Game\Platform\Steam\steamapps\common\MonsterHunterWilds\MHWILDS_EXTRACT\re_chunk_000" # 示例路径
    # 日志目录将基于 test_data_dir
    # default_log_base_dir = Path(default_test_data_dir) / "validation_logs" 

    # --- 用户输入配置 ---
    editor_exe_str = get_user_input("010Editor.exe 路径", default_editor_exe)
    editor_exe = Path(editor_exe_str) if editor_exe_str else Path(default_editor_exe)

    template_file_str = get_user_input("模板 (.bt) 文件路径", default_template_file)
    template_file = Path(template_file_str) if template_file_str else Path(default_template_file)

    test_data_dir_str = get_user_input("测试数据根目录", default_test_data_dir)
    test_data_dir = Path(test_data_dir_str) if test_data_dir_str else Path(default_test_data_dir)
    
    # 日志基础目录，默认为测试数据目录下的 "validation_logs" 子文件夹
    default_log_base_dir_for_prompt = test_data_dir.resolve() / "validation_logs"
    log_base_dir_str = get_user_input("日志文件存放目录", str(default_log_base_dir_for_prompt))
    log_base_dir = Path(log_base_dir_str) if log_base_dir_str else default_log_base_dir_for_prompt


    print(f"\n当前配置:")
    print(f"  编辑器: {editor_exe.resolve()}")
    print(f"  模板: {template_file.resolve()}")
    print(f"  数据目录: {test_data_dir.resolve()}")
    print(f"  日志目录: {log_base_dir.resolve()}\n")

    process_recursively = get_user_input("是否递归处理子目录? (yes/no)", "yes", input_type=bool)
    file_pattern_str = get_user_input(
        "输入文件匹配模式 (例如: *.efx.*, 或正则表达式)",
        "*.efx.*"
    )
    skip_ok_files = get_user_input("是否跳过先前OK列表中的文件? (yes/no)", "yes", input_type=bool)

    use_noui = get_user_input("是否使用 -noui (无界面模式)? (yes/no)", "yes", input_type=bool)
    use_exit_param = get_user_input("是否使用 -exit (010Editor处理后退出)? (yes/no)", "no", input_type=bool)
    timeout_seconds = get_user_input("单个文件处理超时时间 (秒)", 60, input_type=int)
    num_threads_default = os.cpu_count()
    if num_threads_default is None: num_threads_default = 4 # Fallback if cpu_count fails
    num_threads = get_user_input("并行线程数", num_threads_default, input_type=int)

    # --- 验证路径 ---
    if not editor_exe.exists() or not editor_exe.is_file():
        print(f"错误: 010 Editor可执行文件未找到或不是一个文件: '{editor_exe}'")
        sys.exit(1)
    if not template_file.exists() or not template_file.is_file():
        print(f"错误: 模板文件未找到或不是一个文件: '{template_file}'")
        sys.exit(1)
    if not test_data_dir.exists() or not test_data_dir.is_dir():
        print(f"错误: 测试数据目录未找到或不是一个目录: '{test_data_dir}'")
        sys.exit(1)

    try:
        log_base_dir.mkdir(parents=True, exist_ok=True)
        print(f"日志将保存到目录: {log_base_dir.resolve()} (已创建或已存在)")
    except OSError as e:
        print(f"错误: 无法创建日志目录 '{log_base_dir.resolve()}': {e}")
        sys.exit(1)

    # --- 生成带时间戳的日志文件名 ---
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_log_file_path = log_base_dir / f"validation_log_{timestamp}.md"
    ok_files_log_path = log_base_dir / f"ok_files_{timestamp}.txt"
    error_files_log_path = log_base_dir / f"error_files_{timestamp}.txt"


    # --- 加载先前OK的文件列表 (如果用户选择跳过) ---
    previously_ok_abs_paths = set()
    if skip_ok_files:
        previously_ok_abs_paths = load_previously_ok_files_from_txt(log_base_dir)


    # --- 编译文件匹配模式 ---
    compile_error_message = None # 初始化
    try:
        if any(c in file_pattern_str for c in ['^', '$', '+', '?', '(', ')', '[', ']', '{', '}']):
            file_regex = re.compile(file_pattern_str)
            is_regex_pattern = True
            pattern_type_message = f"使用正则表达式模式: `{file_pattern_str}`"
        else:
            is_regex_pattern = False
            pattern_type_message = f"使用Glob通配符模式: `{file_pattern_str}`"
        print(pattern_type_message.replace('`',''))
    except re.error as e:
        compile_error_message = f"错误: 无效的正则表达式模式 '{file_pattern_str}': {e}"
        print(compile_error_message)
        with open(md_log_file_path, "w", encoding="utf-8") as err_log_f: # 尝试写入错误到主日志
            err_log_f.write(f"# 010 Editor 模板验证日志 ({timestamp})\n\n")
            err_log_f.write(f"## 启动错误\n\n{compile_error_message}\n")
        sys.exit(1)

    # --- 文件发现与过滤 ---
    print("\n正在发现文件...")
    all_found_files = []
    if process_recursively:
        for p_root, _, p_filenames in os.walk(test_data_dir):
            for p_filename in p_filenames:
                all_found_files.append(Path(p_root) / p_filename)
    else:
        for p_item in test_data_dir.iterdir():
            if p_item.is_file():
                all_found_files.append(p_item)
    
    files_to_process_initially = [] 
    for file_path_obj in all_found_files: # 使用更有意义的变量名
        filename_only = file_path_obj.name
        if is_regex_pattern:
            if file_regex.match(filename_only):
                files_to_process_initially.append(file_path_obj)
        else:
            if glob.fnmatch.fnmatch(filename_only, file_pattern_str):
                files_to_process_initially.append(file_path_obj)
    
    initial_match_count = len(files_to_process_initially)
    skipped_count = 0
    files_to_process_final = []

    if skip_ok_files and previously_ok_abs_paths:
        for fp_obj in files_to_process_initially:
            if fp_obj.resolve() not in previously_ok_abs_paths:
                files_to_process_final.append(fp_obj)
            else:
                skipped_count += 1
        print(f"根据先前OK文件列表，将跳过 {skipped_count} 个文件。")
    else:
        files_to_process_final = files_to_process_initially

    actual_files_to_process_count = len(files_to_process_final)

    if not files_to_process_final:
        print("没有找到需要处理的文件 (可能所有匹配文件都已在OK列表中并被跳过，或无匹配文件)。正在退出。")
        with open(md_log_file_path, "w", encoding="utf-8") as log_f:
            log_f.write(f"# 010 Editor 模板验证日志 ({timestamp})\n\n")
            log_f.write(f"## 配置\n")
            log_f.write(f"- **编辑器:** `{editor_exe.resolve()}`\n")
            log_f.write(f"- **模板:** `{template_file.resolve()}`\n")
            log_f.write(f"- **数据目录 (根):** `{test_data_dir.resolve()}`\n")
            log_f.write(f"- **文件匹配模式:** `{file_pattern_str}`\n")
            log_f.write(f"- **跳过先前OK文件:** {'是' if skip_ok_files else '否'}\n")
            log_f.write(f"\n在 `{test_data_dir.resolve()}` 中没有找到与模式 `{file_pattern_str}` 匹配且需要处理的文件。\n")
            if initial_match_count > 0 and skipped_count == initial_match_count:
                log_f.write(f"总共匹配到 {initial_match_count} 个文件，全部因先前在OK列表中而被跳过。\n")
        sys.exit(0)

    print(f"共发现 {initial_match_count} 个匹配模式的文件。")
    if skipped_count > 0:
        print(f"跳过了 {skipped_count} 个先前在OK列表中的文件。")
    print(f"准备处理 {actual_files_to_process_count} 个文件，使用 {num_threads} 个线程...")

    # --- 初始化日志文件 ---
    processed_results = [] # 存储所有线程的结果
    
    with open(md_log_file_path, "w", encoding="utf-8") as md_log_f, \
         open(ok_files_log_path, "w", encoding="utf-8") as ok_log_f, \
         open(error_files_log_path, "w", encoding="utf-8") as error_log_f:

        md_log_f.write(f"# 010 Editor 模板验证日志 ({timestamp})\n\n")
        md_log_f.write(f"## 配置\n")
        md_log_f.write(f"- **编辑器:** `{editor_exe.resolve()}`\n")
        md_log_f.write(f"- **模板:** `{template_file.resolve()}`\n")
        md_log_f.write(f"- **数据目录 (根):** `{test_data_dir.resolve()}`\n")
        md_log_f.write(f"- **递归处理:** {'是' if process_recursively else '否'}\n")
        md_log_f.write(f"- **文件匹配模式:** `{file_pattern_str}` ({'正则表达式' if is_regex_pattern else 'Glob通配符'})\n")
        md_log_f.write(f"- **跳过先前OK文件:** {'是' if skip_ok_files else '否'}")
        if skip_ok_files and previously_ok_abs_paths:
             md_log_f.write(f" (从先前OK列表加载了 {len(previously_ok_abs_paths)} 个记录)\n")
        else:
            md_log_f.write("\n")
        md_log_f.write(f"- **主日志文件 (MD):** `{md_log_file_path.resolve()}`\n")
        md_log_f.write(f"- **OK文件列表 (TXT):** `{ok_files_log_path.resolve()}`\n")
        md_log_f.write(f"- **Error文件列表 (TXT):** `{error_files_log_path.resolve()}`\n")
        md_log_f.write(f"- **使用 -noui:** {'是' if use_noui else '否'}\n")
        md_log_f.write(f"- **使用 -exit:** {'是' if use_exit_param else '否'}\n")
        md_log_f.write(f"- **单个文件超时:** {timeout_seconds}秒\n")
        md_log_f.write(f"- **线程数:** {num_threads}\n\n")
        if compile_error_message: 
             md_log_f.write(f"**启动时错误:**\n```\n{compile_error_message}\n```\n\n")
        
        md_log_f.write(f"## 处理日志 (共 {initial_match_count} 个文件匹配模式，计划处理 {actual_files_to_process_count} 个)\n\n")
        if skipped_count > 0:
            md_log_f.write(f"*注意: 已跳过 {skipped_count} 个先前在OK列表中的文件。*\n\n")
        md_log_f.write("| 状态 | 文件路径 (可点击) | 详情 |\n")
        md_log_f.write("|---|---|---|\n")
        md_log_f.flush()

        # --- 多线程处理 ---
        log_lock = threading.Lock() 
        processed_files_count_current_run = 0

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {
                executor.submit(
                    process_file_with_editor,
                    fp_obj.resolve(), # 确保传入的是绝对路径
                    editor_exe,
                    template_file,
                    use_noui,
                    use_exit_param,
                    timeout_seconds,
                    test_data_dir # 传递 test_data_dir 作为 base_data_dir
                ): fp_obj for fp_obj in files_to_process_final
            }

            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                processed_results.append(result) # 收集结果

                with log_lock: # 保护计数器和控制台输出
                    processed_files_count_current_run += 1
                
                console_display_path = result['relative_path'] # 使用 result 中已计算好的相对路径
                print(f"({processed_files_count_current_run}/{actual_files_to_process_count}) {result['status']}: {console_display_path}")
        
        # --- 处理完成后，排序并写入日志 ---
        processed_results.sort(key=lambda r: r['path']) 

        final_ok_list_count = 0
        final_error_list_count = 0

        for result in processed_results:
            file_path_abs_str = result['path'] 
            file_display_name = result['filename']
            
            # URL编码路径中的特殊字符，确保Markdown链接正确
            # 将所有反斜杠替换为正斜杠，然后编码
            path_for_link = file_path_abs_str.replace(os.sep, '/')
            file_link_path_encoded = urllib.parse.quote(path_for_link, safe="/:")
            file_link = f"[{file_display_name}](file:///{file_link_path_encoded})"
            
            details_md = result['message']
            if result['status'] != "OK":
                if result['stdout']:
                    details_md += f"<br><br>**标准输出 (Stdout):**<br>```\n{result['stdout']}\n```"
                if result['stderr']:
                    details_md += f"<br><br>**标准错误 (Stderr):**<br>```\n{result['stderr']}\n```"
            
            details_md_sanitized = details_md.replace("|", "\\|").replace("\n", "<br>")
            md_log_f.write(f"| {result['status']} | {file_link} | {details_md_sanitized} |\n")

            if result['status'] == "OK":
                ok_log_f.write(f"{file_path_abs_str}\n")
                final_ok_list_count += 1
            else:
                error_log_f.write(f"{file_path_abs_str}\n")
                final_error_list_count +=1
        
        md_log_f.flush()
        ok_log_f.flush()
        error_log_f.flush()

        # --- 总结 ---
        md_log_f.write(f"\n## 验证总结\n")
        md_log_f.write(f"- 匹配模式的文件总数: {initial_match_count}\n")
        if skipped_count > 0:
            md_log_f.write(f"- 因先前在OK列表中而被跳过的文件数: {skipped_count}\n")
        md_log_f.write(f"- 本次实际处理的文件数: {processed_files_count_current_run}\n")
        md_log_f.write(f"- 本次处理结果OK的文件数: {final_ok_list_count}\n")
        md_log_f.write(f"- 本次处理结果非OK的文件数: {final_error_list_count}\n")


        if final_error_list_count > 0:
            md_log_f.write(f"- **发现错误、警告或超时的文件 ({final_error_list_count} 个):**\n")
            print(f"\n--- 发现错误、警告或超时的文件 ({final_error_list_count} 个): ---")
            # 从 processed_results 中筛选出错误项，用于总结
            error_summary_items = [res for res in processed_results if res['status'] != "OK"]
            for i, res in enumerate(error_summary_items):
                path_for_summary_link = res['path'].replace(os.sep, '/')
                file_link_path_encoded_summary = urllib.parse.quote(path_for_summary_link, safe='/:')
                file_link_summary = f"[{res['filename']}](file:///{file_link_path_encoded_summary})"

                md_log_f.write(f"  {i+1}. {file_link_summary} - {res['status']}: {res['message']}\n")
                
                console_display_path_err = res['relative_path']
                print(f"  {i+1}. {console_display_path_err} - {res['status']}: {res['message']}")
        else:
            if processed_files_count_current_run > 0:
                msg = "所有本次处理的文件均未检测到错误或超时。"
                md_log_f.write(f"- {msg}\n")
                print(f"\n{msg}")
            elif initial_match_count == 0 :
                msg = "没有文件匹配模式以供处理。"
                md_log_f.write(f"- {msg}\n")
                print(f"\n{msg}")
            elif skipped_count == initial_match_count and initial_match_count > 0:
                msg = f"所有 {initial_match_count} 个匹配文件因先前在OK列表中而被跳过，本次未处理任何文件。"
                md_log_f.write(f"- {msg}\n")
                print(f"\n{msg}")


    print(f"\n验证完成。")
    print(f"  主日志 (MD): {md_log_file_path.resolve()}")
    print(f"  OK 文件列表: {ok_files_log_path.resolve()}")
    print(f"  Error 文件列表: {error_files_log_path.resolve()}")
    print(f"您可以使用Markdown查看器或支持 file:/// 链接的浏览器打开主日志。")

if __name__ == "__main__":
    validate_templates()
