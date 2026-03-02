import os
import shutil
import tarfile
import tempfile

import requests
import tqdm
import zstandard

import utils


class DebPackage:
    def __init__(self, url, cache_dir=None):
        self.tar = None
        self.tempdir = tempfile.mkdtemp()  # always needed for tar extraction
        self.error = None
        debname = url.split("/")[-1]
        # Use cached deb if available
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            debpath = os.path.abspath(os.path.join(cache_dir, debname))
            if os.path.isfile(debpath):
                self.tar = self._get_data_tar(debpath)
                return
        else:
            debpath = os.path.join(self.tempdir, debname)
        # Download
        try:
            r = requests.get(url, stream=True)
        except Exception as exception:
            self.error = str(exception)
            return
        if r.status_code != 200:
            self.error = f"GET request returned {r.status_code}"
            return
        total = int(r.headers.get("Content-Length", 0)) or None
        with open(debpath, "wb+") as f, tqdm.tqdm(
            total=total, unit="B", unit_scale=True, unit_divisor=1024,
            desc=debname, leave=False
        ) as bar:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                bar.update(len(chunk))
        # extract data.tar from deb to the tempdir
        self.tar = self._get_data_tar(debpath)

    def _extract_file_deb(self, deb, name, folder="."):
        # args = ["x", "--output", folder, deb, name] (binutils >= 2.34)
        _, stderr = utils.run_ar(["x", deb, name], cwd=folder)
        if not stderr:
            return os.path.join(folder, name)
        return None

    def _get_data_tar(self, debpath):
        folder = self.tempdir
        for ext in ("gz", "xz"):
            tar_name = f"data.tar.{ext}"
            tar_path = self._extract_file_deb(debpath, tar_name, folder=folder)
            if tar_path:
                return tarfile.open(tar_path, f"r:{ext}")
        # tarfile doesn't support .zst
        # do it ourselves with zstandard
        tar_zst_name = "data.tar.zst"
        tar_zst_path = self._extract_file_deb(debpath, tar_zst_name, folder=folder)
        if not tar_zst_path:
            self.error = "Failed to find data.tar"
            return None
        dctx = zstandard.ZstdDecompressor()
        tar_path = os.path.join(folder, "data.tar")
        with open(tar_zst_path, "rb") as ifh, open(tar_path, "wb+") as ofh:
            dctx.copy_stream(ifh, ofh)
        return tarfile.open(tar_path, "r:")

    def close(self):
        if self.tar:
            self.tar.close()
            self.tar = None
        if self.tempdir:
            shutil.rmtree(self.tempdir)
            self.tempdir = None

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.close()
