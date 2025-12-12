import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QFileDialog, QLabel, 
                            QTableWidget, QTableWidgetItem, QHeaderView,
                            QGroupBox, QMessageBox, QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont
from PIL import Image
from PIL.ExifTags import TAGS
import struct

# 尝试导入HEIC支持
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False

class ExifWorker(QObject):
    """EXIF数据提取工作线程"""
    finished = pyqtSignal(list)
    progress = pyqtSignal(int, int)  # current, total
    error = pyqtSignal(str)
    
    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths
    
    def process_files(self):
        results = []
        total_files = len(self.file_paths)
        
        for i, filepath in enumerate(self.file_paths):
            try:
                old_name = os.path.basename(filepath)
                _, ext = os.path.splitext(old_name)
                
                # 检查HEIC支持
                if ext.lower() in ['.heic', '.heif'] and not HEIC_SUPPORT:
                    result = {
                        'filepath': filepath,
                        'old_name': old_name,
                        'date_time': None,
                        'camera_model': None,
                        'error': 'NO_HEIC_SUPPORT',
                        'new_name': f"NOHEIC_{old_name}"
                    }
                else:
                    # 获取EXIF信息（深度增强版，仅使用PIL）
                    date_time, camera_model, error_msg = self.get_advanced_exif_data(filepath)
                    
                    if error_msg and "错误:" in error_msg:
                        result = {
                            'filepath': filepath,
                            'old_name': old_name,
                            'date_time': None,
                            'camera_model': None,
                            'error': 'EXIF_ERROR',
                            'new_name': f"ERROR_{old_name}"
                        }
                    elif date_time == "未知时间":
                        result = {
                            'filepath': filepath,
                            'old_name': old_name,
                            'date_time': "无时间信息",
                            'camera_model': "无相机信息",
                            'error': 'NO_EXIF_TIME',
                            'new_name': f"NOEXIF_{old_name}"
                        }
                    else:
                        # 构造基础文件名
                        base_name = f"{date_time}_{camera_model}"
                        result = {
                            'filepath': filepath,
                            'old_name': old_name,
                            'date_time': date_time,
                            'camera_model': camera_model,
                            'error': None,
                            'base_name': base_name,
                            'extension': ext
                        }
                
                results.append(result)
                
            except Exception as e:
                results.append({
                    'filepath': filepath,
                    'old_name': os.path.basename(filepath),
                    'date_time': None,
                    'camera_model': None,
                    'error': 'PROCESS_ERROR',
                    'new_name': f"ERROR_{os.path.basename(filepath)}"
                })
            
            # 发送进度更新
            self.progress.emit(i + 1, total_files)
        
        self.finished.emit(results)
    
    def get_advanced_exif_data(self, filepath):
        """高级EXIF数据获取，使用PIL的多种方法"""
        try:
            # 方法1: 使用PIL的getexif()方法
            try:
                image = Image.open(filepath)
                exifdata = image.getexif()
                if exifdata:
                    date_time, camera_model = self.parse_exif_with_pil(exifdata)
                    if date_time and date_time != "未知时间":
                        return date_time, camera_model, None
            except Exception as e:
                pass
            
            # 方法2: 尝试使用_exif实例变量
            try:
                image = Image.open(filepath)
                if hasattr(image, '_getexif'):
                    exifdata = image._getexif()
                    if exifdata:
                        date_time, camera_model = self.parse_exif_with_pil(exifdata)
                        if date_time and date_time != "未知时间":
                            return date_time, camera_model, None
            except Exception as e:
                pass
            
            # 方法3: 尝试直接访问_exif属性
            try:
                image = Image.open(filepath)
                if hasattr(image, '_exif') and image._exif:
                    date_time, camera_model = self.parse_exif_with_pil(image._exif)
                    if date_time and date_time != "未知时间":
                        return date_time, camera_model, None
            except Exception as e:
                pass
            
            # 方法4: 尝试从raw exif数据中提取
            try:
                date_time, camera_model = self.parse_raw_exif(filepath)
                if date_time and date_time != "未知时间":
                    return date_time, camera_model, None
            except Exception as e:
                pass
            
            # 如果以上方法都失败，返回未知时间
            return "未知时间", "Unknown", "无EXIF信息"
            
        except Exception as e:
            return "未知时间", "Unknown", f"错误: {str(e)}"
    
    def parse_exif_with_pil(self, exifdata):
        """使用PIL方式解析EXIF数据"""
        # 定义时间字段的优先级顺序
        time_fields = [
            "DateTimeOriginal",    # 原始拍摄时间（最高优先级）
            "DateTime",           # 修改时间
            "DateTimeDigitized",  # 数字化时间
            "CreateDate",         # 创建时间（苹果设备）
            "ModifyDate"          # 修改时间（苹果设备）
        ]
        
        date_time = None
        camera_model = "Unknown"
        
        # 按优先级查找时间信息
        for field in time_fields:
            for tag_id in exifdata:
                tag = TAGS.get(tag_id, tag_id)
                if tag == field:
                    raw_value = exifdata.get(tag_id)
                    # 处理不同类型的值
                    if isinstance(raw_value, bytes):
                        value = raw_value.decode('utf-8', errors='ignore').strip()
                    elif isinstance(raw_value, str):
                        value = raw_value.strip()
                    else:
                        value = str(raw_value).strip()
                    
                    if value and value != "0000:00:00 00:00:00":
                        date_time = value
                        break
                # 同时查找相机型号
                elif tag == "Model":
                    raw_value = exifdata.get(tag_id)
                    if isinstance(raw_value, bytes):
                        camera_model = raw_value.decode('utf-8', errors='ignore').strip().replace(" ", "")
                    elif isinstance(raw_value, str):
                        camera_model = raw_value.strip().replace(" ", "")
                    else:
                        camera_model = str(raw_value).strip().replace(" ", "")
                elif tag == "Make":  # 如果没有Model，尝试使用Make
                    raw_value = exifdata.get(tag_id)
                    if isinstance(raw_value, bytes):
                        make = raw_value.decode('utf-8', errors='ignore').strip()
                    elif isinstance(raw_value, str):
                        make = raw_value.strip()
                    else:
                        make = str(raw_value).strip()
                    
                    if make and camera_model == "Unknown":
                        camera_model = make.replace(" ", "")
            if date_time:
                break
        
        # 如果仍然没有找到时间信息，尝试遍历所有标签
        if not date_time:
            for tag_id in exifdata:
                tag = TAGS.get(tag_id, tag_id)
                if tag in time_fields:
                    raw_value = exifdata.get(tag_id)
                    if isinstance(raw_value, bytes):
                        value = raw_value.decode('utf-8', errors='ignore').strip()
                    elif isinstance(raw_value, str):
                        value = raw_value.strip()
                    else:
                        value = str(raw_value).strip()
                    
                    if value and value != "0000:00:00 00:00:00":
                        date_time = value
                        break
                elif tag == "Model":
                    raw_value = exifdata.get(tag_id)
                    if isinstance(raw_value, bytes):
                        camera_model = raw_value.decode('utf-8', errors='ignore').strip().replace(" ", "")
                    elif isinstance(raw_value, str):
                        camera_model = raw_value.strip().replace(" ", "")
                    else:
                        camera_model = str(raw_value).strip().replace(" ", "")
                elif tag == "Make":
                    raw_value = exifdata.get(tag_id)
                    if isinstance(raw_value, bytes):
                        make = raw_value.decode('utf-8', errors='ignore').strip()
                    elif isinstance(raw_value, str):
                        make = raw_value.strip()
                    else:
                        make = str(raw_value).strip()
                    
                    if make and camera_model == "Unknown":
                        camera_model = make.replace(" ", "")
        
        # 格式化日期时间
        if date_time:
            formatted_datetime = self.format_datetime_string(date_time)
            if formatted_datetime != "未知时间":
                return formatted_datetime, camera_model
        
        return "未知时间", camera_model
    
    def parse_raw_exif(self, filepath):
        """直接从文件中解析EXIF数据（低级方法）"""
        try:
            with open(filepath, 'rb') as f:
                # 检查是否是JPEG文件
                header = f.read(2)
                if header != b'\xff\xd8':
                    return "未知时间", "Unknown"
                
                f.seek(0)
                # 跳过JFIF头
                f.read(2)
                
                while True:
                    marker = f.read(2)
                    if not marker or len(marker) < 2:
                        break
                    
                    if marker[0:1] != b'\xff':
                        break
                    
                    if marker[1:2] in b'\xe1':  # APP1标记，通常包含EXIF
                        length = struct.unpack('>H', f.read(2))[0]
                        exif_data = f.read(length - 2)
                        
                        if exif_data.startswith(b'Exif\x00\x00'):
                            # 解析TIFF头
                            tiff_data = exif_data[6:]
                            return self.parse_tiff_data(tiff_data)
                    
                    elif marker[1:2] in b'\xe0\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xeb\xec\xed\xee\xef':
                        # 其他APP段，跳过
                        length = struct.unpack('>H', f.read(2))[0]
                        f.seek(length - 2, os.SEEK_CUR)
                    else:
                        break
                        
        except Exception as e:
            pass
        
        return "未知时间", "Unknown"
    
    def parse_tiff_data(self, tiff_data):
        """解析TIFF格式的EXIF数据"""
        try:
            if len(tiff_data) < 8:
                return "未知时间", "Unknown"
            
            # 检查字节顺序
            byte_order = tiff_data[:2]
            if byte_order == b'II':
                endian = '<'  # Little endian
            elif byte_order == b'MM':
                endian = '>'  # Big endian
            else:
                return "未知时间", "Unknown"
            
            # 检查TIFF标识
            tiff_id = struct.unpack(endian + 'H', tiff_data[2:4])[0]
            if tiff_id != 42:
                return "未知时间", "Unknown"
            
            # 获取第一个IFD偏移
            ifd_offset = struct.unpack(endian + 'L', tiff_data[4:8])[0]
            
            # 解析IFD
            date_time, camera_model = self.parse_ifd(tiff_data, ifd_offset, endian)
            return date_time, camera_model
            
        except Exception as e:
            return "未知时间", "Unknown"
    
    def parse_ifd(self, tiff_data, offset, endian):
        """解析图像文件目录(IFD)"""
        try:
            if offset + 2 > len(tiff_data):
                return "未知时间", "Unknown"
            
            num_entries = struct.unpack(endian + 'H', tiff_data[offset:offset+2])[0]
            entry_start = offset + 2
            
            date_time = "未知时间"
            camera_model = "Unknown"
            
            for i in range(num_entries):
                entry_offset = entry_start + i * 12
                if entry_offset + 12 > len(tiff_data):
                    continue
                    
                entry_data = tiff_data[entry_offset:entry_offset+12]
                if len(entry_data) < 12:
                    continue
                
                tag_id = struct.unpack(endian + 'H', entry_data[0:2])[0]
                data_type = struct.unpack(endian + 'H', entry_data[2:4])[0]
                count = struct.unpack(endian + 'L', entry_data[4:8])[0]
                value_offset = struct.unpack(endian + 'L', entry_data[8:12])[0]
                
                # 查找时间相关标签 (DateTimeOriginal=36867, DateTime=306, DateTimeDigitized=36868)
                if tag_id in [306, 36867, 36868]:  # DateTime, DateTimeOriginal, DateTimeDigitized
                    if count < 20:  # 日期时间字符串通常不会太长
                        if count <= 4:  # 值直接存储在offset字段中
                            value_data = entry_data[8:12]
                        else:
                            # 从指定偏移处读取数据
                            if value_offset < len(tiff_data):
                                value_data = tiff_data[value_offset:value_offset+count]
                                if len(value_data) >= count:
                                    try:
                                        date_str = value_data.decode('utf-8', errors='ignore').strip('\x00')
                                        if date_str and date_str != "0000:00:00 00:00:00":
                                            formatted_time = self.format_datetime_string(date_str)
                                            if formatted_time != "未知时间":
                                                date_time = formatted_time
                                    except:
                                        pass
                elif tag_id == 272:  # Model
                    if count <= 4:
                        value_data = entry_data[8:12]
                    else:
                        if value_offset < len(tiff_data):
                            value_data = tiff_data[value_offset:value_offset+count]
                            if len(value_data) >= count:
                                try:
                                    model_str = value_data.decode('utf-8', errors='ignore').strip('\x00').strip().replace(" ", "")
                                    if model_str:
                                        camera_model = model_str
                                except:
                                    pass
                elif tag_id == 271:  # Make
                    if count <= 4:
                        value_data = entry_data[8:12]
                    else:
                        if value_offset < len(tiff_data):
                            value_data = tiff_data[value_offset:value_offset+count]
                            if len(value_data) >= count:
                                try:
                                    make_str = value_data.decode('utf-8', errors='ignore').strip('\x00').strip().replace(" ", "")
                                    if make_str and camera_model == "Unknown":
                                        camera_model = make_str
                                except:
                                    pass
            
            return date_time, camera_model
            
        except Exception as e:
            return "未知时间", "Unknown"
    
    def format_datetime_string(self, date_time_str):
        """格式化日期时间字符串"""
        if not date_time_str:
            return "未知时间"
        
        # 确保是字符串
        if isinstance(date_time_str, bytes):
            date_time_str = date_time_str.decode('utf-8', errors='ignore')
        elif not isinstance(date_time_str, str):
            date_time_str = str(date_time_str)
        
        # 常见的时间格式
        formats = [
            "%Y:%m:%d %H:%M:%S",      # 标准EXIF格式
            "%Y-%m-%d %H:%M:%S",     # 常见格式
            "%Y/%m/%d %H:%M:%S",     # 另一种格式
            "%Y:%m:%d %H:%M:%S.%f",  # 带毫秒
            "%Y-%m-%d %H:%M:%S.%f",  # 带毫秒
            "%Y-%m-%dT%H:%M:%S",     # ISO格式
            "%Y-%m-%dT%H:%M:%SZ",    # ISO格式带Z
            "%Y:%m:%d %H:%M",        # 没有秒
            "%Y-%m-%d %H:%M",        # 没有秒
            "%Y/%m/%d %H:%M",        # 没有秒
        ]
        
        for fmt in formats:
            try:
                dt_obj = datetime.strptime(date_time_str.strip(), fmt)
                return dt_obj.strftime("%Y%m%d_%H%M%S")
            except ValueError:
                continue
        
        return "未知时间"

class RenameWorker(QObject):
    """文件重命名工作线程"""
    finished = pyqtSignal(int, int)  # success_count, error_count
    progress = pyqtSignal(int, int)  # current, total
    
    def __init__(self, rename_tasks):
        super().__init__()
        self.rename_tasks = rename_tasks
    
    def rename_files(self):
        success_count = 0
        error_count = 0
        total_files = len(self.rename_tasks)
        
        for i, task in enumerate(self.rename_tasks):
            try:
                old_path = task['filepath']
                new_path = task['new_path']
                
                # 检查目标文件是否已存在，避免覆盖
                counter = 1
                original_new_path = new_path
                while os.path.exists(new_path):
                    name_part = f"{task['base_name']}_{counter}"
                    new_path = os.path.join(os.path.dirname(old_path), f"{name_part}{task['extension']}")
                    counter += 1
                
                os.rename(old_path, new_path)
                success_count += 1
                
            except Exception as e:
                error_count += 1
                print(f"重命名失败 {task['filepath']}: {str(e)}")
            
            self.progress.emit(i + 1, total_files)
        
        self.finished.emit(success_count, error_count)

class PhotoRenamerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EXIF照片批量重命名工具")
        self.setGeometry(100, 100, 1000, 800)
        
        self.selected_files = []
        self.preview_results = []
        self.rename_completed = False
        self.init_ui()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 顶部区域 - 文件夹选择
        folder_group = QGroupBox("照片文件夹")
        folder_layout = QVBoxLayout()
        
        # 文件夹选择行
        path_layout = QHBoxLayout()
        self.folder_label = QLabel("未选择文件夹")
        self.folder_label.setStyleSheet("font-weight: bold; color: #555;")
        path_layout.addWidget(self.folder_label)
        
        browse_btn = QPushButton("浏览文件夹")
        browse_btn.clicked.connect(self.select_folder)
        path_layout.addWidget(browse_btn)
        
        folder_layout.addLayout(path_layout)
        
        # 文件统计和操作按钮
        stats_layout = QHBoxLayout()
        
        self.stats_label = QLabel("文件统计: 0 张图片")
        stats_layout.addWidget(self.stats_label)
        
        # 预览和重命名按钮组
        action_layout = QHBoxLayout()
        self.preview_btn = QPushButton("🔍 预览文件名")
        self.preview_btn.clicked.connect(self.preview_names)
        self.preview_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        action_layout.addWidget(self.preview_btn)
        
        self.rename_btn = QPushButton("🔄 开始重命名")
        self.rename_btn.setEnabled(False)
        self.rename_btn.clicked.connect(self.rename_files)
        self.rename_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        action_layout.addWidget(self.rename_btn)
        
        stats_layout.addLayout(action_layout)
        
        folder_layout.addLayout(stats_layout)
        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)
        
        # 进度条容器（隐藏时占位）
        self.progress_container = QFrame()
        progress_layout = QVBoxLayout(self.progress_container)
        self.progress_container.setFixedHeight(40)
        
        # 预览进度条
        self.preview_progress = QProgressBar()
        self.preview_progress.setVisible(False)
        self.preview_progress.setTextVisible(True)
        progress_layout.addWidget(self.preview_progress)
        
        # 重命名进度条
        self.rename_progress = QProgressBar()
        self.rename_progress.setVisible(False)
        self.rename_progress.setTextVisible(True)
        progress_layout.addWidget(self.rename_progress)
        
        layout.addWidget(self.progress_container)
        
        # HEIC支持提示
        if not HEIC_SUPPORT:
            heic_warning = QLabel("⚠️ 注意: 未安装HEIC支持库，HEIC文件将无法读取EXIF信息")
            heic_warning.setStyleSheet("color: orange; font-size: 12px;")
            layout.addWidget(heic_warning)
        
        # 预览表格
        table_label = QLabel("📋 预览结果:")
        table_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(table_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["原文件名", "拍摄时间", "相机型号", "新文件名"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        
        layout.addWidget(self.table)
        
        # 状态栏
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("状态: 等待选择文件夹...")
        self.status_label.setStyleSheet("font-style: italic; color: #666;")
        status_layout.addWidget(self.status_label)
        
        # 重置按钮
        reset_btn = QPushButton("🔄 重新选择")
        reset_btn.clicked.connect(self.reset_all)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                padding: 5px 10px;
                border-radius: 3px;
                font-size: 11px;
            }
        """)
        status_layout.addWidget(reset_btn)
        
        layout.addLayout(status_layout)
    
    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择照片文件夹")
        if folder_path:
            self.reset_all()  # 重置所有状态
            
            self.folder_label.setText(folder_path)
            
            # 获取所有图片文件
            image_extensions = {
                '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', 
                '.cr2', '.nef', '.arw', '.dng', '.orf', '.rw2', '.pef',
                '.heic', '.heif'
            }
            files = []
            for filename in os.listdir(folder_path):
                name, ext = os.path.splitext(filename)
                if ext.lower() in image_extensions:
                    files.append(os.path.join(folder_path, filename))
            
            self.selected_files = sorted(files)
            self.stats_label.setText(f"文件统计: {len(self.selected_files)} 张图片")
            self.status_label.setText(f"状态: 找到 {len(self.selected_files)} 张图片")
            
            # 如果文件数量适中，自动预览
            if 0 < len(self.selected_files) <= 500:
                self.status_label.setText(f"状态: 找到 {len(self.selected_files)} 张图片，正在自动预览...")
                # 延迟执行预览，让用户看到状态变化
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(500, self.preview_names)
    
    def reset_all(self):
        """重置所有状态"""
        self.selected_files.clear()
        self.preview_results.clear()
        self.table.setRowCount(0)
        self.rename_btn.setEnabled(False)
        self.preview_btn.setEnabled(True)
        self.rename_completed = False
        self.folder_label.setText("未选择文件夹")
        self.stats_label.setText("文件统计: 0 张图片")
        self.status_label.setText("状态: 等待选择文件夹...")
        self.preview_progress.setVisible(False)
        self.rename_progress.setVisible(False)
        self.progress_container.setVisible(False)
    
    def preview_names(self):
        if not self.selected_files:
            QMessageBox.warning(self, "警告", "请先选择包含图片的文件夹")
            return
        
        # 显示进度条容器
        self.progress_container.setVisible(True)
        
        # 显示进度条，禁用按钮
        self.preview_btn.setEnabled(False)
        self.preview_progress.setVisible(True)
        self.preview_progress.setMaximum(len(self.selected_files))
        self.preview_progress.setValue(0)
        self.status_label.setText("状态: 正在分析文件...")
        
        # 创建工作线程
        self.exif_thread = QThread()
        self.exif_worker = ExifWorker(self.selected_files)
        self.exif_worker.moveToThread(self.exif_thread)
        
        # 连接信号
        self.exif_thread.started.connect(self.exif_worker.process_files)
        self.exif_worker.finished.connect(self.on_preview_finished)
        self.exif_worker.progress.connect(self.on_preview_progress)
        self.exif_worker.error.connect(self.on_preview_error)
        self.exif_worker.finished.connect(self.exif_thread.quit)
        self.exif_worker.finished.connect(self.exif_worker.deleteLater)
        self.exif_thread.finished.connect(self.exif_thread.deleteLater)
        
        # 启动线程
        self.exif_thread.start()
    
    def on_preview_progress(self, current, total):
        self.preview_progress.setValue(current)
        percentage = int((current / total) * 100)
        self.preview_progress.setFormat(f"预览分析中... {current}/{total} ({percentage}%)")
        self.status_label.setText(f"状态: 分析中... ({current}/{total})")
    
    def on_preview_error(self, error_msg):
        QMessageBox.critical(self, "错误", f"预览过程中发生错误: {error_msg}")
        self.reset_preview_ui()
    
    def on_preview_finished(self, results):
        self.preview_results = results
        self.update_preview_table(results)
        self.reset_preview_ui()
        
        # 统计成功数量
        success_count = sum(1 for r in results if r['error'] is None)
        error_count = len(results) - success_count
        
        self.status_label.setText(f"状态: 预览完成 - 成功 {success_count} 个, 错误 {error_count} 个")
        
        # 只有在未完成重命名的情况下才启用重命名按钮
        if not self.rename_completed:
            self.rename_btn.setEnabled(success_count > 0)
            if success_count > 0:
                self.status_label.setText(f"状态: 预览完成 - 准备重命名 {success_count} 个文件")
        else:
            self.status_label.setText(f"状态: 已完成重命名 - 成功 {success_count} 个, 失败 {error_count} 个")
    
    def reset_preview_ui(self):
        self.preview_btn.setEnabled(True)
        self.preview_progress.setVisible(False)
        # 如果两个进度条都隐藏，隐藏进度条容器
        if not self.rename_progress.isVisible():
            self.progress_container.setVisible(False)
    
    def update_preview_table(self, results):
        self.table.setRowCount(len(results))
        
        # 用于生成唯一文件名
        used_names = set()
        
        for i, result in enumerate(results):
            if result['error'] is None:
                # 生成唯一文件名
                base_name = result['base_name']
                ext = result['extension']
                new_name = self.generate_unique_filename_preview(base_name, ext, used_names)
                used_names.add(new_name)
                
                self.table.setItem(i, 0, QTableWidgetItem(result['old_name']))
                self.table.setItem(i, 1, QTableWidgetItem(result['date_time']))
                self.table.setItem(i, 2, QTableWidgetItem(result['camera_model']))
                self.table.setItem(i, 3, QTableWidgetItem(new_name))
            else:
                self.table.setItem(i, 0, QTableWidgetItem(result['old_name']))
                self.table.setItem(i, 1, QTableWidgetItem("读取失败"))
                self.table.setItem(i, 2, QTableWidgetItem("读取失败"))
                self.table.setItem(i, 3, QTableWidgetItem(result['new_name']))
                
                # 设置背景色
                if result['error'] == 'NO_HEIC_SUPPORT':
                    self.table.item(i, 0).setBackground(Qt.GlobalColor.red)
                elif result['error'] == 'NO_EXIF_TIME':
                    self.table.item(i, 0).setBackground(Qt.GlobalColor.yellow)
                else:
                    self.table.item(i, 0).setBackground(Qt.GlobalColor.red)
    
    def generate_unique_filename_preview(self, base_name, extension, existing_names):
        """预览模式下的唯一文件名生成"""
        candidate = f"{base_name}{extension}"
        if candidate not in existing_names:
            return candidate
        
        counter = 1
        while True:
            candidate = f"{base_name}_{counter}{extension}"
            if candidate not in existing_names:
                return candidate
            counter += 1
    
    def rename_files(self):
        # 检查是否已经完成重命名
        if self.rename_completed:
            QMessageBox.information(self, "提示", "文件已经完成重命名！\n如需重新处理，请选择新的文件夹。")
            return
        
        if not self.preview_results:
            QMessageBox.warning(self, "警告", "请先进行预览")
            return
        
        # 准备重命名任务
        rename_tasks = []
        used_names = set()
        
        for result in self.preview_results:
            if result['error'] is None:
                # 生成实际重命名路径
                folder_path = os.path.dirname(result['filepath'])
                base_name = result['base_name']
                ext = result['extension']
                
                # 生成唯一文件名（基于当前文件系统状态）
                new_name = self.generate_unique_filename_actual(base_name, ext, folder_path, used_names)
                used_names.add(new_name)
                
                new_path = os.path.join(folder_path, new_name)
                rename_tasks.append({
                    'filepath': result['filepath'],
                    'new_path': new_path,
                    'base_name': base_name,
                    'extension': ext
                })
        
        if not rename_tasks:
            QMessageBox.warning(self, "警告", "没有可重命名的文件")
            return
        
        reply = QMessageBox.question(self, "确认", 
                                   f"确定要重命名 {len(rename_tasks)} 个文件吗？\n此操作不可撤销！",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 设置重命名完成标志为True，防止重复点击
        self.rename_completed = True
        
        # 显示进度条容器
        self.progress_container.setVisible(True)
        
        # 显示重命名进度
        self.rename_btn.setEnabled(False)
        self.rename_progress.setVisible(True)
        self.rename_progress.setMaximum(len(rename_tasks))
        self.rename_progress.setValue(0)
        self.status_label.setText("状态: 正在重命名文件...")
        
        # 创建重命名线程
        self.rename_thread = QThread()
        self.rename_worker = RenameWorker(rename_tasks)
        self.rename_worker.moveToThread(self.rename_thread)
        
        # 连接信号
        self.rename_thread.started.connect(self.rename_worker.rename_files)
        self.rename_worker.finished.connect(self.on_rename_finished)
        self.rename_worker.progress.connect(self.on_rename_progress)
        self.rename_worker.finished.connect(self.rename_thread.quit)
        self.rename_worker.finished.connect(self.rename_worker.deleteLater)
        self.rename_thread.finished.connect(self.rename_thread.deleteLater)
        
        # 启动线程
        self.rename_thread.start()
    
    def on_rename_progress(self, current, total):
        self.rename_progress.setValue(current)
        percentage = int((current / total) * 100)
        self.rename_progress.setFormat(f"重命名中... {current}/{total} ({percentage}%)")
        self.status_label.setText(f"状态: 重命名中... ({current}/{total})")
    
    def on_rename_finished(self, success_count, error_count):
        self.reset_rename_ui()
        QMessageBox.information(self, "完成", 
                              f"🎉 重命名完成!\n成功: {success_count} 个\n失败: {error_count} 个")
        self.status_label.setText(f"状态: 🎉 重命名完成 - 成功 {success_count}, 失败 {error_count}")
        
        # 保持重命名完成状态，按钮保持禁用
        self.rename_btn.setEnabled(False)
    
    def reset_rename_ui(self):
        self.rename_progress.setVisible(False)
        # 如果两个进度条都隐藏，隐藏进度条容器
        if not self.preview_progress.isVisible():
            self.progress_container.setVisible(False)
    
    def generate_unique_filename_actual(self, base_name, extension, folder_path, used_names):
        """实际重命名时的唯一文件名生成（考虑文件系统）"""
        candidate = f"{base_name}{extension}"
        full_path = os.path.join(folder_path, candidate)
        
        # 检查是否已在本次重命名中使用
        if candidate in used_names or os.path.exists(full_path):
            counter = 1
            while True:
                candidate = f"{base_name}_{counter}{extension}"
                full_path = os.path.join(folder_path, candidate)
                if candidate not in used_names and not os.path.exists(full_path):
                    break
                counter += 1
        
        return candidate

def main():
    app = QApplication(sys.argv)
    
    # 设置应用字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    window = PhotoRenamerApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()