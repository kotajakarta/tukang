import io
import os
import stat
import tarfile
import tempfile
import pytest
from app.services import files_agent
from app.services.files_agent import AgentError, IgnoreRules

# The ignore list of a real project's .vscode/sftp.json (VS Code SFTP extension)
SFTP_JSON_IGNORE = [
    "node_modules", ".git", ".env", ".next", ".env.local", ".env.*.local", "*.log", "runlocal.sh",
    "pull.sh", "deploy.sh", "dev.sh", "push.sh", ".container", ".claude", "stitch", "CLAUDE.md",
    ".vscode", ".antigravity", "docs/*.*", "uploads", ".github", ".worktrees", "logs",
]

@pytest.mark.parametrize("rel,is_dir", [
    ("node_modules", True), ("frontend/node_modules", True), ("frontend/node_modules/x/index.js", False),
    (".env", False), ("backend/.env", False), (".env.production.local", False),
    ("logs", True), ("var/app.log", False), ("docs/readme.md", False), ("CLAUDE.md", False),
    ("uploads/a.png", False),
])
def test_ignore_rules_match_sftp_json_semantics(rel, is_dir):
    assert IgnoreRules(SFTP_JSON_IGNORE).ignored(rel, is_dir)

@pytest.mark.parametrize("rel,is_dir", [
    ("src/app.py", False), ("src/docs/readme.md", False), ("docs", True), ("docs/sub/guide", True),
    (".env.example", False), ("environment.ts", False), ("src/logs.ts", False), ("CLAUDE.md.bak", False),
])
def test_ignore_rules_keep_project_files(rel, is_dir):
    assert not IgnoreRules(SFTP_JSON_IGNORE).ignored(rel, is_dir)

def test_ignore_rules_gitignore_extras():
    rules = IgnoreRules(["# comment", "", "build/", "/top.txt", "**/cache/**", "*.tmp", "!keep.tmp", "file[0-9].txt"])
    assert rules.ignored("build", True) and not rules.ignored("build", False)  # trailing slash: dirs only
    assert rules.ignored("top.txt", False) and not rules.ignored("sub/top.txt", False)  # leading slash anchors
    assert rules.ignored("a/cache/b/c.bin", False)
    assert rules.ignored("x.tmp", False) and not rules.ignored("keep.tmp", False)  # negation, last match wins
    assert rules.ignored("file7.txt", False) and not rules.ignored("fileX.txt", False)

@pytest.fixture
def tree():
    with tempfile.TemporaryDirectory(prefix="tukang-sync-") as d:
        src, dst = os.path.join(d, "src"), os.path.join(d, "dst")
        os.makedirs(f"{src}/app/node_modules/pkg")
        os.makedirs(f"{src}/docs/sub")
        os.makedirs(f"{src}/empty")
        for rel, body in {
            "app/main.py": "print('v2')\n", "app/node_modules/pkg/i.js": "x", "app/debug.log": "noise",
            ".env": "SECRET=local", "docs/a.md": "doc", "docs/sub/b.md": "nested doc", "run.sh": "#!/bin/sh\n",
        }.items():
            with open(f"{src}/{rel}", "w") as f:
                f.write(body)
        os.chmod(f"{src}/run.sh", 0o755)
        os.symlink("app/main.py", f"{src}/latest")
        os.makedirs(dst)
        yield src, dst

def _pack(root, rels, ignore=()):
    buf = io.BytesIO()
    files_agent.op_pack({"root": root, "rels": rels, "ignore": list(ignore)}, buf)
    return io.BytesIO(buf.getvalue())

def test_pack_unpack_roundtrip_overwrites_and_keeps_extra_files(tree):
    src, dst = tree
    os.makedirs(f"{dst}/app")
    with open(f"{dst}/app/main.py", "w") as f:
        f.write("print('v1')\n")
    with open(f"{dst}/.env", "w") as f:
        f.write("SECRET=production")
    with open(f"{dst}/only-on-destination.txt", "w") as f:
        f.write("keep me")

    ignore = ["node_modules", ".env", "*.log", "docs/*.*"]
    scan = files_agent.op_scan({"root": src, "rels": ["."], "ignore": ignore})
    result = files_agent.op_unpack({"root": dst}, _pack(src, ["."], ignore))

    assert open(f"{dst}/app/main.py").read() == "print('v2')\n"  # overwritten
    assert open(f"{dst}/.env").read() == "SECRET=production"  # ignored: production config untouched
    assert open(f"{dst}/only-on-destination.txt").read() == "keep me"  # never deleted
    assert not os.path.exists(f"{dst}/app/node_modules") and not os.path.exists(f"{dst}/app/debug.log")
    assert not os.path.exists(f"{dst}/docs/a.md") and open(f"{dst}/docs/sub/b.md").read() == "nested doc"
    assert os.path.isdir(f"{dst}/empty")
    assert os.readlink(f"{dst}/latest") == "app/main.py"
    assert stat.S_IMODE(os.stat(f"{dst}/run.sh").st_mode) == 0o755
    assert result["files"] == scan["files"] == 3  # main.py, run.sh, docs/sub/b.md
    assert scan["ignored"] == 4  # node_modules, debug.log, .env, docs/a.md
    assert not [n for n in os.listdir(dst) if n.startswith(".tukang-")]

def test_explicitly_selected_ignored_path_is_skipped(tree):
    src, dst = tree
    scan = files_agent.op_scan({"root": src, "rels": [".env", "app/main.py"], "ignore": [".env"]})
    assert scan["skipped"] == [".env"] and scan["files"] == 1
    files_agent.op_unpack({"root": dst}, _pack(src, [".env", "app/main.py"], [".env"]))
    assert not os.path.exists(f"{dst}/.env") and os.path.exists(f"{dst}/app/main.py")

def test_pack_refuses_missing_path_before_writing(tree):
    src, _ = tree
    buf = io.BytesIO()
    with pytest.raises(FileNotFoundError):
        files_agent.op_pack({"root": src, "rels": ["nope"], "ignore": []}, buf)
    assert buf.getvalue() == b""

def test_unpack_creates_missing_destination_root(tree):
    src, dst = tree
    files_agent.op_unpack({"root": f"{dst}/new/deep"}, _pack(src, ["run.sh"]))
    assert os.path.exists(f"{dst}/new/deep/run.sh")

def _evil_tar(*members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, kind, extra in members:
            info = tarfile.TarInfo(name)
            if kind == "sym":
                info.type, info.linkname = tarfile.SYMTYPE, extra
                tar.addfile(info)
            else:
                data = (extra or "x").encode()
                info.size = len(data)
                info.mode = 0o4755 if kind == "suid" else 0o644
                tar.addfile(info, io.BytesIO(data))
    return io.BytesIO(buf.getvalue())

@pytest.mark.parametrize("name", ["../escape.txt", "/tmp/absolute.txt", "a/../../escape.txt", "./a/./b"])
def test_unpack_refuses_unsafe_names(tree, name):
    _, dst = tree
    with pytest.raises(AgentError):
        files_agent.op_unpack({"root": dst}, _evil_tar((name, "file", None)))
    assert not os.path.exists(os.path.join(os.path.dirname(dst), "escape.txt"))

def test_unpack_refuses_writing_through_escaping_symlink(tree):
    _, dst = tree
    outside = os.path.join(os.path.dirname(dst), "outside")
    os.makedirs(outside)
    with pytest.raises(AgentError, match="symlink"):
        files_agent.op_unpack({"root": dst}, _evil_tar(("link", "sym", outside), ("link/pwned.txt", "file", "owned")))
    assert os.listdir(outside) == []

def test_unpack_allows_symlink_inside_root_and_drops_setuid(tree):
    _, dst = tree
    os.makedirs(f"{dst}/real")
    os.symlink("real", f"{dst}/alias")
    files_agent.op_unpack({"root": dst}, _evil_tar(("alias/f.txt", "file", "ok"), ("tool", "suid", "bin")))
    assert open(f"{dst}/real/f.txt").read() == "ok"
    assert stat.S_IMODE(os.stat(f"{dst}/tool").st_mode) == 0o755

def test_unpack_refuses_replacing_directory_with_file(tree):
    _, dst = tree
    os.makedirs(f"{dst}/thing/inner")
    with pytest.raises(AgentError, match="directory"):
        files_agent.op_unpack({"root": dst}, _evil_tar(("thing", "file", "x")))
    assert os.path.isdir(f"{dst}/thing/inner")

def test_unpack_refuses_protected_root():
    with pytest.raises(AgentError):
        files_agent.op_unpack({"root": "/etc"}, _evil_tar(("x", "file", None)))

def test_unpack_new_directory_swapped_for_symlink_is_not_chmodded(tree, monkeypatch):
    # Race: whoever can write the destination swaps a just-created directory for a link before its
    # mode/owner are applied; they must never land on the link target
    src, dst = tree
    victim = os.path.join(os.path.dirname(dst), "victim-dir")
    os.makedirs(victim)
    os.chmod(victim, 0o700)
    real_mkdir = os.mkdir

    def racing_mkdir(path, mode=0o777):
        real_mkdir(path, mode)
        if os.fsdecode(path).endswith("/evil"):
            os.rmdir(path)
            os.symlink(victim, path)

    monkeypatch.setattr(files_agent.os, "mkdir", racing_mkdir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("evil")
        info.type, info.mode = tarfile.DIRTYPE, 0o777
        tar.addfile(info)
    with pytest.raises((AgentError, OSError)):
        files_agent.op_unpack({"root": dst}, io.BytesIO(buf.getvalue()))
    assert stat.S_IMODE(os.stat(victim).st_mode) == 0o700

def test_paste_copy_never_writes_through_link_planted_at_destination(tree, monkeypatch):
    # Race: a link appears at the free destination name between the existence check and the copy
    src, dst = tree
    victim = os.path.join(os.path.dirname(dst), "victim.txt")
    with open(victim, "w") as f:
        f.write("ORIGINAL\n")
    planted = f"{dst}/main.py"
    os.symlink(victim, planted)
    monkeypatch.setattr(files_agent, "_unique_dest", lambda dest_dir, name: planted)
    with pytest.raises(OSError):
        files_agent.op_paste({"paths": [f"{src}/app/main.py"], "dest_dir": dst, "mode": "copy"})
    assert open(victim).read() == "ORIGINAL\n"
