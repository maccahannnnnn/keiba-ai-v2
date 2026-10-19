"""Shared deterministic semantic-tree identity for Current PRE and EXP-024."""
import hashlib
import json
from pathlib import Path


def tree_hash(path: Path, *, error_factory=RuntimeError, hash_file=None) -> str:
    if not path.is_dir():
        raise error_factory('STOP_ENVIRONMENT_TREE_MISSING:' + str(path))
    allowed={'.py','.json','.toml','.yaml','.yml','.ini','.cfg','.csv'}
    ignored={'__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','cache','tmp','temp','.tmp'}
    if hash_file is None:
        hash_file=lambda item: hashlib.sha256(item.read_bytes()).hexdigest()
    files=[]
    for item in path.rglob('*'):
        relative=item.relative_to(path)
        if any(part.lower() in ignored for part in relative.parts):continue
        if item.suffix.lower() not in allowed or not item.is_file():continue
        if item.is_symlink():raise error_factory('STOP_ENVIRONMENT_TREE_SYMLINK:' + str(item))
        files.append(item)
    digest=hashlib.sha256()
    for item in sorted(files,key=lambda x:x.relative_to(path).as_posix()):
        value={'relative_path':item.relative_to(path).as_posix(),'sha256':hash_file(item)}
        digest.update((json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',', ':'),allow_nan=False)+'\n').encode('utf-8'))
    return digest.hexdigest()
