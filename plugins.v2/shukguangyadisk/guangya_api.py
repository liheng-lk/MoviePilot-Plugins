"""MoviePilot 存储接口兼容层。

在原 GuangYaApi 实现上补齐新版 MoviePilot 接口，并增强上传完成确认与可选进度日志。
"""

from datetime import datetime
from hashlib import md5
from pathlib import Path
from time import monotonic
from typing import Optional
from urllib.parse import urlparse

from app import schemas
from app.log import logger
from app.modules.filemanager.storages import transfer_process

from .guangya_api_legacy import GuangYaApi as _GuangYaApi


class GuangYaApi(_GuangYaApi):
    """在原光鸭云盘实现上增加新版 MoviePilot 兼容与上传诊断。"""

    upload_progress_log: bool = False

    def get_item_strict(self, path: Path) -> Optional[schemas.FileItem]:
        """严格查询文件或目录；当前远端实现沿用 get_item 的查询语义。"""
        return self.get_item(path)

    @staticmethod
    def _fmt_bytes(size: int) -> str:
        """格式化字节大小。"""
        value = float(size or 0)
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        return f"{value:.2f} {units[index]}"

    def _confirm_uploaded_item(
        self,
        target_dir_path: str,
        target_name: str,
        file_size: int,
        max_try: int = 20,
        interval: float = 0.5,
    ) -> Optional[schemas.FileItem]:
        """上传任务回执缺失时，按目标目录中的同名同大小文件兜底确认。"""
        item = self._wait_item_visible(
            parent_path=target_dir_path,
            name=target_name,
            expected_type="file",
            max_try=max_try,
            interval=interval,
        )
        if not item:
            return None
        if item.size not in (None, 0, file_size):
            logger.warning(
                "【光鸭云盘助手】【上传】发现同名文件但大小不一致: %s, local=%s, remote=%s",
                target_name,
                file_size,
                item.size,
            )
            return None
        self._cache_item(item)
        return item

    def _upload_single_file(
        self,
        folder_id: str,
        local_path: Path,
        target_dir_path: str,
        target_name: str = None,
    ) -> Optional[schemas.FileItem]:
        """上传单个文件，并提供实时进度日志与上传后可见性兜底确认。"""
        target_name = target_name or local_path.name
        target_path = Path(target_dir_path) / target_name
        file_size = local_path.stat().st_size
        started_at = monotonic()

        logger.info(
            "【光鸭云盘助手】【上传】开始: %s -> %s, 大小=%s",
            local_path,
            target_path,
            self._fmt_bytes(file_size),
        )

        hash_md5 = md5()
        with open(local_path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(4 * 1024 * 1024), b""):
                hash_md5.update(chunk)
        file_md5 = hash_md5.hexdigest().upper()

        if self.upload_progress_log:
            logger.info("【光鸭云盘助手】【上传】MD5 完成: %s, md5=%s", target_name, file_md5)

        mp_progress = transfer_process(local_path.as_posix())
        last_logged_bucket = -1

        def progress(consumed: int, total: int) -> None:
            """同时上报 MoviePilot 进度，并按 5%% 粒度输出日志。"""
            nonlocal last_logged_bucket
            if not total:
                return
            percent = max(0.0, min(100.0, consumed * 100 / total))
            mp_progress(percent)
            if not self.upload_progress_log:
                return
            bucket = int(percent // 5) * 5
            if bucket <= last_logged_bucket and percent < 100:
                return
            last_logged_bucket = bucket
            elapsed = max(monotonic() - started_at, 0.001)
            speed = consumed / elapsed
            logger.info(
                "【光鸭云盘助手】【上传】进度: %s %d%% (%s/%s), 平均速度=%s/s",
                target_name,
                int(percent),
                self._fmt_bytes(consumed),
                self._fmt_bytes(total),
                self._fmt_bytes(speed),
            )

        try:
            flash_response = self.client.check_flash_upload(
                task_id="",
                gcid=file_md5,
                file_size=file_size,
                file_name=target_name,
                parent_id=folder_id,
            )
            if flash_response.get("msg") == "success" and flash_response.get("data"):
                data = flash_response.get("data", {}) or {}
                mp_progress(100)
                elapsed = monotonic() - started_at
                logger.info(
                    "【光鸭云盘助手】【上传】秒传成功: %s, fileId=%s, 耗时=%.2fs",
                    target_name,
                    data.get("fileId", ""),
                    elapsed,
                )
                return schemas.FileItem(
                    storage=self._disk_name,
                    fileid=str(data.get("fileId", "")),
                    path=str(target_path),
                    type="file",
                    name=data.get("fileName", target_name),
                    basename=Path(target_name).stem,
                    extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                    pickcode=str(data),
                    size=file_size,
                    modify_time=int(datetime.now().timestamp()),
                )
        except Exception as err:
            logger.debug("【光鸭云盘助手】【上传】秒传检查失败: %s - %s", target_name, err)

        try:
            response = self.client.get_upload_token(
                file_name=target_name,
                file_size=file_size,
                file_md5=file_md5,
                parent_id=folder_id,
                capacity=2,
            )

            if response.get("code") == 156:
                task_id = (response.get("data", {}) or {}).get("taskId", "")
                if self.upload_progress_log:
                    logger.info("【光鸭云盘助手】【上传】服务端任务已存在: %s, task_id=%s", target_name, task_id)
                if task_id and self._wait_task_done(task_id):
                    task_response = self.client.get_file_info_by_task_id(task_id)
                    data = task_response.get("data", {}) or {}
                    file_id = str(data.get("fileId", ""))
                    if file_id:
                        self._cache_path_id(str(target_path), file_id)
                        mp_progress(100)
                        logger.info("【光鸭云盘助手】【上传】任务完成: %s, fileId=%s", target_name, file_id)
                        return schemas.FileItem(
                            storage=self._disk_name,
                            fileid=file_id,
                            path=str(target_path),
                            type="file",
                            name=data.get("fileName", target_name),
                            basename=Path(target_name).stem,
                            extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                            pickcode=str(data),
                            size=file_size,
                            modify_time=int(datetime.now().timestamp()),
                        )
                confirmed = self._confirm_uploaded_item(target_dir_path, target_name, file_size)
                if confirmed:
                    mp_progress(100)
                    logger.info("【光鸭云盘助手】【上传】通过目录可见性确认成功: %s, fileId=%s", target_name, confirmed.fileid)
                    return confirmed

            if response.get("msg") != "success" and response.get("code") != 0:
                logger.error("【光鸭云盘助手】【上传】获取上传凭证失败: %s - %s", target_name, response)
                return None

            data = response.get("data", {}) or {}
            task_id = data.get("taskId", "")
            object_path = data.get("objectPath", "")
            bucket_name = data.get("bucketName", "")
            endpoint = data.get("endPoint", "") or data.get("fullEndPoint", "")
            creds = data.get("creds", {}) or {}
            access_key_id = creds.get("accessKeyID", "")
            secret_access_key = creds.get("secretAccessKey", "")
            session_token = creds.get("sessionToken", "")

            if self.upload_progress_log:
                logger.info("【光鸭云盘助手】【上传】凭证获取成功: %s, task_id=%s", target_name, task_id)

            if endpoint and bucket_name and object_path and access_key_id and secret_access_key and session_token:
                parsed = urlparse(endpoint if endpoint.startswith("http") else f"https://{endpoint}")
                host = parsed.netloc or parsed.path
                if bucket_name and host.startswith(bucket_name + "."):
                    host = host[len(bucket_name) + 1 :]
                self.client.upload_file_multipart(
                    endpoint=f"https://{host}",
                    bucket_name=bucket_name,
                    object_path=object_path,
                    file_path=str(local_path),
                    oss_access_key_id=access_key_id,
                    oss_access_key_secret=secret_access_key,
                    security_token=session_token,
                    progress_callback=progress,
                )

            if task_id:
                self._wait_task_done(task_id)
                task_response = self.client.get_file_info_by_task_id(task_id)
                task_data = task_response.get("data", {}) or {}
                file_id = str(task_data.get("fileId", ""))
                if file_id:
                    self._cache_path_id(str(target_path), file_id)
                    mp_progress(100)
                    uploaded_item = schemas.FileItem(
                        storage=self._disk_name,
                        fileid=file_id,
                        path=str(target_path),
                        type="file",
                        name=task_data.get("fileName", target_name),
                        basename=Path(target_name).stem,
                        extension=Path(target_name).suffix[1:] if Path(target_name).suffix else None,
                        pickcode=str(task_data),
                        size=file_size,
                        modify_time=int(datetime.now().timestamp()),
                    )
                    self._cache_item(uploaded_item)
                    elapsed = max(monotonic() - started_at, 0.001)
                    logger.info(
                        "【光鸭云盘助手】【上传】完成: %s, fileId=%s, 耗时=%.2fs, 平均速度=%s/s",
                        target_name,
                        file_id,
                        elapsed,
                        self._fmt_bytes(file_size / elapsed),
                    )
                    return uploaded_item

            confirmed = self._confirm_uploaded_item(target_dir_path, target_name, file_size)
            if confirmed:
                mp_progress(100)
                elapsed = max(monotonic() - started_at, 0.001)
                logger.warning(
                    "【光鸭云盘助手】【上传】任务回执缺少 fileId，但目标文件已确认存在，按成功返回: %s, fileId=%s, 耗时=%.2fs",
                    target_name,
                    confirmed.fileid,
                    elapsed,
                )
                return confirmed

            logger.error("【光鸭云盘助手】【上传】失败: %s，上传后未能确认目标文件", target_name)
            return None
        except Exception as err:
            confirmed = self._confirm_uploaded_item(target_dir_path, target_name, file_size, max_try=10)
            if confirmed:
                mp_progress(100)
                logger.warning(
                    "【光鸭云盘助手】【上传】过程出现异常但目标文件已存在，按成功返回: %s, error=%s",
                    target_name,
                    err,
                )
                return confirmed
            logger.error("【光鸭云盘助手】【上传】失败: %s - %s", target_name, err)
            return None
