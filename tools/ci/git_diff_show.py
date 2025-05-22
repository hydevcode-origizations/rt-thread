# 
# Copyright (c) 2025, RT-Thread Development Team
#
# SPDX-License-Identifier: Apache-2.0
#
# Change Logs:
# Date           Author       Notes
# 2025-05-15     supperthomas add PR status show
#

# 流程:
# 获取diff
# 整理输出修改报告
# 获取修改列表
# 根据策略整理出需要编译的地方，并返回列表
import subprocess
import sys
import os
import re
import argparse
import locale
from typing import List, Dict

import json
from typing import List
import shutil
import fnmatch
class FileDiff:
    def __init__(self, path: str, status: str, size_change: int = 0, old_size: int = 0, new_size: int = 0):
        self.path = path
        self.status = status  # A (added), M (modified), D (deleted), R (renamed)
        self.size_change = size_change
        self.old_size = old_size
        self.new_size = new_size
        
    def __str__(self):
        if self.status == 'A':
            return f"Added {self.path}: {self.size_change} bytes"
        elif self.status == 'D':
            return f"Deleted {self.path}: was {self.old_size} bytes"
        elif self.status == 'M' or self.status == 'R':
            return f"Modified {self.path}: {self.size_change} bytes change"
        else:
            return f"{self.status} {self.path}"
            
class GitDiffAnalyzer:
    def __init__(self, target_branch: str):
        self.target_branch = target_branch
        self.encoding = locale.getpreferredencoding()

    def get_diff_files(self) -> List[FileDiff]:
        """获取当前分支与目标分支之间的差异文件"""
        # 找到当前分支和目标分支的最近共同祖先
        merge_base = self.get_merge_base()
        if not merge_base:
            print("No common ancestor found between current branch and target branch")
            sys.exit(1)
            
        # 获取差异文件列表
        diff_cmd = f"git diff --name-status {merge_base}"
        print(diff_cmd)
        try:
            output = subprocess.check_output(diff_cmd.split(), stderr=subprocess.STDOUT)
            output = output.decode(self.encoding).strip()
            print(output)
        except subprocess.CalledProcessError as e:
            print(f"Error executing git diff: {e.output.decode(self.encoding)}")
            sys.exit(1)
            
        if not output:

            # shutil.copy(".github/ALL_BSP_COMPILE.json", ".github/ALL_BSP_COMPILE_TEMP.json")
            print("No differences between current branch and target branch")

            sys.exit(0)
            
        # 处理可能的换行符问题
        output = output.replace('\r\n', '\n')
        lines = output.split('\n')
        
        file_diffs = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            parts = line.split('\t')
            if len(parts) < 2:
                # 可能是重命名文件，格式为 "RXXX\told_path\tnew_path"
                match = re.match(r'R(\d+)\t(.+)\t(.+)', line)
                if match:
                    status = 'R'
                    old_path = match.group(2)
                    new_path = match.group(3)
                    # 计算重命名文件的修改大小
                    old_size = self.get_file_size(old_path, self.target_branch)
                    new_size = self.get_file_size(new_path, 'HEAD')
                    size_change = new_size - old_size if old_size > 0 else new_size
                    file_diffs.append(FileDiff(new_path, status, size_change, old_size, new_size))
            else:
                status = parts[0][0]  # 取状态码的第一个字符
                path = parts[1]
                
                if status == 'A':
                    # 新增文件，计算大小
                    size = self.get_file_size(path, 'HEAD')
                    file_diffs.append(FileDiff(path, status, size, 0, size))
                elif status == 'D':
                    # 删除文件，计算原大小
                    size = self.get_file_size(path, self.target_branch)
                    file_diffs.append(FileDiff(path, status, 0, size, 0))
                elif status == 'M':
                    # 修改文件，计算大小变化
                    old_size = self.get_file_size(path, self.target_branch)
                    new_size = self.get_file_size(path, 'HEAD')
                    size_change = new_size - old_size
                    file_diffs.append(FileDiff(path, status, size_change, old_size, new_size))
                    
        return file_diffs

    def get_merge_base(self) -> str:
        """获取当前分支和目标分支的最近共同祖先"""
        try:
            cmd = f"git merge-base {self.target_branch} HEAD"
            print(cmd)
            output = subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            return output.decode(self.encoding).strip()
        except subprocess.CalledProcessError as e:
            print(f"Error executing git merge-base: {e.output.decode(self.encoding)}")
            return None

    def get_file_size(self, path: str, ref: str) -> int:
        """获取指定分支上文件的大小"""
        try:
            # 使用 git cat-file 来获取文件内容，然后计算其大小
            cmd = f"git cat-file blob {ref}:{path}"
            output = subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            return len(output)
        except subprocess.CalledProcessError:
            # 如果文件不存在或无法获取，返回0
            return 0

def format_size(size: int) -> str:
    """将字节大小转换为人类可读的格式"""
    if size < 1024:
        return f"{size} bytes"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"

def is_bsp(path):
    return os.path.isfile(os.path.join(path, "rtconfig.h"))

def filter_bsp_config(file_diffs: List[FileDiff], config_path: str):
    # 读取原始JSON配置
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 获取所有修改的文件路径（统一使用Linux风格路径）
    modified_paths = [diff.path.replace('\\', '/') for diff in file_diffs]
    print(modified_paths)
    if not modified_paths:
        print("master分支运行")
        return

    bsp_paths = set()
    bsp_in_but_not_bsp_paths = set()
    all_print_paths = set()
    for modified_path in modified_paths:
        parts = modified_path.strip(os.sep).split('/')
        if not parts:
            continue
        first_level = parts[0]
        first_level_path = os.path.join(os.getcwd(), first_level)

        #处理bsp路径的逻辑
        if first_level == "bsp":
            temp_path=os.path.join(os.getcwd(), modified_path)
            # 判断是否是文件
            if not os.path.isdir(modified_path):
                temp_path = os.path.dirname(temp_path)

            #循环搜索每一级是否有rtconfig.h
            while temp_path !=first_level_path:
                if is_bsp(temp_path):
                    bsp_paths.add(temp_path)
        
                    break
                temp_path=os.path.dirname(temp_path)

            if temp_path ==first_level_path:
                bsp_in_but_not_bsp_paths.add(parts[1])

        else:
            #非bsp路径逻辑
            all_print_paths.add(first_level_path)

    # 变成相对路径
    bsp_list = set()
    for path in sorted(bsp_paths):
        current_working_dir = os.path.join(os.getcwd(), "bsp/")
        if path.startswith(current_working_dir):
            bsp_list.add(path[len(current_working_dir):].lstrip(os.sep))
        else:
            bsp_list.add(path)  # 如果 first_level_path 不以 current_working_dir 开头，则保持不变

    # 处理修改了bsp外的文件的情况
    filtered_bsp = [
        path for path in bsp_list
        if path.split('/')[0] not in bsp_in_but_not_bsp_paths
    ]

    merged_result = filtered_bsp + list(bsp_in_but_not_bsp_paths)

    filtered_legs = []
    for leg in config["legs"]:
        matched_paths = [
            path for path in leg.get("SUB_RTT_BSP", [])
            if any(keyword in path for keyword in merged_result)
        ]
        if matched_paths:
            filtered_legs.append({**leg, "SUB_RTT_BSP": matched_paths})

    # 生成新的配置
    new_config = {"legs": filtered_legs}

    # 判断有没有修改到bsp外的文件，有的话则编译全部
    if not all_print_paths:
        print(new_config)
        file_name = ".github/ALL_BSP_COMPILE_TEMP.json"

        # 将 new_config 写入文件
        with open(file_name, "w", encoding="utf-8") as file:
            json.dump(new_config, file, ensure_ascii=False, indent=4)


def main():

        # 源文件路径
    source_file = ".github/ALL_BSP_COMPILE.json"  # 替换为你的文件路径

    # 目标文件路径
    target_file = ".github/ALL_BSP_COMPILE_TEMP.json"  # 替换为你的目标文件路径

    # 读取源文件并过滤掉带有 // 的行
    with open(source_file, "r", encoding="utf-8") as infile, open(target_file, "w", encoding="utf-8") as outfile:
        for line in infile:
            if not line.lstrip().startswith("//"):
                outfile.write(line)
    
    parser = argparse.ArgumentParser(description='Compare current branch with target branch and show file differences.')
    parser.add_argument('target_branch', help='Target branch to compare against (e.g., master)')
    args = parser.parse_args()
    
    analyzer = GitDiffAnalyzer(args.target_branch)
    file_diffs = analyzer.get_diff_files()

    # 生成报告
    generate_report(file_diffs, args.target_branch)

    filter_bsp_config(file_diffs,".github/ALL_BSP_COMPILE_TEMP.json")

    
def add_summary(text):
    """
    add summary to github action.
    """
    os.system(f'echo "{text}" >> $GITHUB_STEP_SUMMARY ;')

def generate_report(file_diffs: List[FileDiff], target_branch: str):
    """生成差异报告"""

    add_summary(f"\n=== Comparison between {target_branch} and current branch ===\n")
    
    # 分类统计
    added_files = [f for f in file_diffs if f.status == 'A']
    removed_files = [f for f in file_diffs if f.status == 'D']
    modified_files = [f for f in file_diffs if f.status == 'M']
    renamed_files = [f for f in file_diffs if f.status == 'R']
    
    # 计算总变化量
    total_added = sum(f.size_change for f in added_files)
    total_removed = sum(f.old_size for f in removed_files)
    total_modified = sum(abs(f.size_change) for f in modified_files)
    # 计算总的大小变化
    total_size_change = sum(f.size_change for f in file_diffs)


    add_summary(f"Total changes: {len(file_diffs)} files")
    add_summary(f"Added: {len(added_files)} files ({format_size(total_added)})")
    add_summary(f"Removed: {len(removed_files)} files ({format_size(total_removed)})")
    add_summary(f"Modified: {len(modified_files)} files ({format_size(total_modified)})")
    add_summary(f"Renamed: {len(renamed_files)} files")
    add_summary(f"\nTotal size change: {format_size(total_size_change)}")
    add_summary("\n" + "="*60 + "\n")
    
    # 显示详细差异
    for diff in file_diffs:
        print(diff)
        
        # 详细展示修改和新增的文件大小
        if diff.status == 'A':
            add_summary(f"  Size: {format_size(diff.new_size)}")
        elif diff.status == 'M':
            add_summary(f"  Original size: {format_size(diff.old_size)}")
            add_summary(f"  New size: {format_size(diff.new_size)}")
            add_summary(f"  Size change: {format_size(abs(diff.size_change))}")
        elif diff.status == 'R':
            add_summary(f"  Original size: {format_size(diff.old_size)}")
            add_summary(f"  New size: {format_size(diff.new_size)}")
            add_summary(f"  Size change: {format_size(abs(diff.size_change))}")
        elif diff.status == 'D':
            add_summary(f"  Original size: {format_size(diff.old_size)}")
            
        add_summary("-" * 50)

if __name__ == "__main__":
    main()