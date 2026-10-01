"""Bind snapshot bytes, code and build to independently inspectable manifest."""
import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def package():
    data=(ROOT/'src/data.json').read_bytes();snapshot=json.loads(data)
    manifest=json.loads((ROOT/'public/radar-manifest.json').read_text())
    manifest['snapshot_sha256']=hashlib.sha256(data).hexdigest()
    try:manifest['deploy_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:manifest['deploy_commit']='로컬·저장소 미생성'
    manifest['html_sha256']=hashlib.sha256((ROOT/'dist/index.html').read_bytes()).hexdigest()
    manifest['public_url_verified']=False
    (ROOT/'dist/radar-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    shutil.copyfile(ROOT/'src/data.json',ROOT/'dist/radar-data.json')
    (ROOT/'dist/.nojekyll').touch()
    print('배포 식별자·데이터 해시 생성 완료')
if __name__=='__main__':package()
