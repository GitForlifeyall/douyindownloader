#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/gdrive_uploader.py
=================================
Uploads generated video, subtitle, and metadata assets directly to Google Drive
using Google Cloud Application Default Credentials (ADC), Service Account JSON,
or User OAuth2 credentials (credentials.json / token.json).
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Union, Dict, Any, List

logger = logging.getLogger("dubbing_studio.gdrive")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import google.auth
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False


class GoogleDriveUploader:
    """Helper to upload files and manage folders directly on Google Drive."""

    SCOPES = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive"
    ]

    def __init__(
        self,
        service_account_json: Optional[Union[str, Path]] = None,
        credentials_json: Optional[Union[str, Path]] = None,
        token_json: Optional[Union[str, Path]] = None
    ):
        if not GDRIVE_AVAILABLE:
            raise ImportError(
                "google-api-python-client and google-auth are required for Google Drive upload. "
                "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
            )

        creds = self._authenticate(
            service_account_json=service_account_json,
            credentials_json=credentials_json,
            token_json=token_json
        )
        self.service = build("drive", "v3", credentials=creds)

    def _authenticate(
        self,
        service_account_json: Optional[Union[str, Path]] = None,
        credentials_json: Optional[Union[str, Path]] = None,
        token_json: Optional[Union[str, Path]] = None
    ):
        """
        Authenticate using one of the following methods:
        1. Service Account JSON file path (explicit, or via GOOGLE_APPLICATION_CREDENTIALS)
        2. OAuth2 User token (token.json or generated from credentials.json)
        3. Application Default Credentials (ADC)
        """
        # 1. Service Account JSON
        sa_candidate = (
            service_account_json
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("GDRIVE_SERVICE_ACCOUNT")
        )
        if sa_candidate and Path(sa_candidate).is_file():
            from google.oauth2 import service_account
            logger.info(f"[GDrive] Authenticating with Service Account: {sa_candidate}")
            return service_account.Credentials.from_service_account_file(
                str(sa_candidate), scopes=self.SCOPES
            )

        # 2. OAuth2 User Token (credentials.json / token.json)
        token_path = Path(token_json or os.getenv("GDRIVE_TOKEN_JSON", "token.json"))
        oauth_client_path = Path(credentials_json or os.getenv("GDRIVE_CREDENTIALS_JSON", "credentials.json"))

        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = None
        if token_path.is_file():
            creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("[GDrive] Refreshing expired OAuth2 user token...")
                creds.refresh(Request())
            elif oauth_client_path.is_file():
                from google_auth_oauthlib.flow import InstalledAppFlow
                logger.info(f"[GDrive] Initiating browser OAuth2 login with: {oauth_client_path}...")
                flow = InstalledAppFlow.from_client_secrets_file(str(oauth_client_path), self.SCOPES)
                creds = flow.run_local_server(port=0)
                with open(token_path, "w", encoding="utf-8") as token_file:
                    token_file.write(creds.to_json())
                logger.info(f"[GDrive] Saved authorized user token to: {token_path}")

        if creds and creds.valid:
            logger.info("[GDrive] Authenticated using OAuth2 User Credentials.")
            return creds

        # 3. Application Default Credentials fallback
        try:
            creds, _ = google.auth.default(scopes=self.SCOPES)
            logger.info("[GDrive] Authenticated using Application Default Credentials.")
            return creds
        except Exception as e:
            raise RuntimeError(
                f"Google Drive authentication failed. No valid Service Account JSON or OAuth2 credentials found. "
                f"Please provide a Service Account JSON path, set GOOGLE_APPLICATION_CREDENTIALS, "
                f"or place a credentials.json client secret in the workspace. Error: {e}"
            )

    def get_or_create_subfolder(
        self,
        folder_name: str,
        parent_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Finds or creates a subfolder in Google Drive under parent_id.
        
        Args:
            folder_name: Name of the folder to find/create.
            parent_id: Parent Google Drive folder ID (optional).
            
        Returns:
            Dict containing 'id' and 'webViewLink'.
        """
        clean_name = folder_name.replace("'", "\\'")
        query_parts = [
            f"name = '{clean_name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false"
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")

        q = " and ".join(query_parts)
        response = self.service.files().list(
            q=q,
            spaces="drive",
            fields="files(id, name, webViewLink)"
        ).execute()

        files = response.get("files", [])
        if files:
            logger.info(f"[GDrive] Found existing folder '{folder_name}' (ID: {files[0]['id']})")
            return files[0]

        # Create folder
        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_id:
            folder_metadata["parents"] = [parent_id]

        created = self.service.files().create(
            body=folder_metadata,
            fields="id, name, webViewLink"
        ).execute()
        logger.info(f"[GDrive] Created new folder '{folder_name}' (ID: {created.get('id')})")
        return created

    def upload_file(
        self,
        local_path: Union[str, Path],
        folder_id: Optional[str] = None,
        custom_name: Optional[str] = None,
        skip_if_exists: bool = True
    ) -> Dict[str, Any]:
        """
        Uploads a local file into a specific Google Drive folder.
        
        Args:
            local_path: Local filesystem path of the file to upload.
            folder_id: The ID of the target Google Drive folder (from its URL).
            custom_name: Optional display name for the file in Drive.
            skip_if_exists: If True, skips uploading if a file with the same name exists in folder_id.
            
        Returns:
            Dict containing file 'id', 'name', and 'webViewLink'.
        """
        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"File to upload does not exist: {path}")

        file_name = custom_name or path.name

        # Check if file already exists in destination
        if skip_if_exists and folder_id:
            clean_name = file_name.replace("'", "\\'")
            q = f"name = '{clean_name}' and '{folder_id}' in parents and trashed = false"
            try:
                res = self.service.files().list(
                    q=q,
                    spaces="drive",
                    fields="files(id, name, webViewLink)"
                ).execute()
                existing = res.get("files", [])
                if existing:
                    logger.info(f"[GDrive] File '{file_name}' already exists in Drive folder. Skipping upload.")
                    return existing[0]
            except Exception:
                pass

        file_metadata: Dict[str, Any] = {
            "name": file_name
        }
        if folder_id:
            file_metadata["parents"] = [folder_id]

        # Determine mimetype
        suffix = path.suffix.lower()
        if suffix == ".mp4":
            mimetype = "video/mp4"
        elif suffix == ".srt":
            mimetype = "text/plain"
        elif suffix == ".json":
            mimetype = "application/json"
        elif suffix in (".wav", ".mp3"):
            mimetype = "audio/mpeg"
        else:
            mimetype = "application/octet-stream"

        media = MediaFileUpload(str(path), mimetype=mimetype, resumable=True)

        logger.info(f"[GDrive] Uploading '{path.name}' ({path.stat().st_size / (1024*1024):.1f} MB) to Drive...")
        file_obj = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink"
        ).execute()

        logger.info(f"[GDrive] Upload complete: {file_obj.get('name')} (ID: {file_obj.get('id')})")
        return file_obj

    def upload_channel_folder(
        self,
        local_channel_dir: Union[str, Path],
        parent_folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a dedicated folder for the channel in Google Drive,
        uploads all videos and channel_metadata.json, and returns a summary dict.
        """
        cdir = Path(local_channel_dir)
        channel_name = cdir.name

        # 1. Get or create folder for this channel in Drive
        drive_folder = self.get_or_create_subfolder(channel_name, parent_id=parent_folder_id)
        folder_id = drive_folder["id"]

        results = {
            "channel_name": channel_name,
            "drive_folder_id": folder_id,
            "drive_folder_link": drive_folder.get("webViewLink"),
            "uploaded_files": []
        }

        # 2. Upload video files
        for video_file in sorted(cdir.glob("*.mp4")):
            try:
                up_res = self.upload_file(video_file, folder_id=folder_id, skip_if_exists=True)
                results["uploaded_files"].append({
                    "filename": video_file.name,
                    "drive_id": up_res.get("id"),
                    "drive_link": up_res.get("webViewLink")
                })
            except Exception as e:
                logger.error(f"[GDrive] Failed to upload {video_file.name}: {e}")

        # 3. Upload caption text files (if any)
        for txt_file in sorted(cdir.glob("*.txt")):
            try:
                self.upload_file(txt_file, folder_id=folder_id, skip_if_exists=True)
            except Exception as e:
                logger.error(f"[GDrive] Failed to upload {txt_file.name}: {e}")

        # 4. Upload metadata JSON
        meta_json = cdir / "channel_metadata.json"
        if meta_json.is_file():
            try:
                up_json = self.upload_file(meta_json, folder_id=folder_id, skip_if_exists=False)
                results["metadata_json_link"] = up_json.get("webViewLink")
            except Exception as e:
                logger.error(f"[GDrive] Failed to upload metadata JSON: {e}")

        return results

    def upload_final_videos_folder(
        self,
        local_dir: Union[str, Path],
        parent_folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uploads ONLY the final output videos and the single master metadata.json to Google Drive.
        Ensures no extraneous text, subtitle, or intermediate files are uploaded.
        """
        cdir = Path(local_dir)
        folder_name = cdir.name

        drive_folder = self.get_or_create_subfolder(folder_name, parent_id=parent_folder_id)
        folder_id = drive_folder["id"]

        results = {
            "folder_name": folder_name,
            "drive_folder_id": folder_id,
            "drive_folder_link": drive_folder.get("webViewLink"),
            "uploaded_files": []
        }

        # 1. Upload final video files only
        for video_file in sorted(cdir.glob("*.mp4")):
            try:
                up_res = self.upload_file(video_file, folder_id=folder_id, skip_if_exists=False)
                results["uploaded_files"].append({
                    "filename": video_file.name,
                    "drive_id": up_res.get("id"),
                    "drive_link": up_res.get("webViewLink")
                })
            except Exception as e:
                logger.error(f"[GDrive] Failed to upload {video_file.name}: {e}")

        # 2. Upload single master metadata.json
        meta_json = cdir / "metadata.json"
        if meta_json.is_file():
            try:
                up_json = self.upload_file(meta_json, folder_id=folder_id, skip_if_exists=False)
                results["metadata_json_link"] = up_json.get("webViewLink")
            except Exception as e:
                logger.error(f"[GDrive] Failed to upload metadata JSON: {e}")

        return results
