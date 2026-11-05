"""Replay the shell repair in disposable fixtures. No router or network access."""
import os
import pathlib
import shlex
import subprocess
import tempfile


def main():
    source = (pathlib.Path(__file__).resolve().parents[1] / "app" / "ssh_keepalive.sh").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="rd03v2-ssh-replay-") as folder:
        root = pathlib.Path(folder)
        commands = root / "bin"
        commands.mkdir()
        state = root / "nvram"
        state.write_text("0\n")
        running = root / "running"
        marker = root / "ready"
        init = root / "dropbear"
        actions = root / "actions"
        original_init = """#!/bin/sh
channel=release
if [ "$channel" = "release" ]; then exit 0; fi
printf '%s\\n' "$1" >> "$TEST_ROOT/actions"
case "$1" in
  restart)
    [ ! -f "$TEST_ROOT/fail" ] || exit 1
    touch "$TEST_ROOT/running"
    ;;
esac
"""
        fixtures = {
            "id": "#!/bin/sh\nprintf '0\\n'\n",
            "pidof": "#!/bin/sh\n[ -f \"$TEST_ROOT/running\" ] || exit 1\nprintf '123\\n'\n",
            "nvram": """#!/bin/sh
case "$1" in
  get) cat "$TEST_ROOT/nvram";;
  set) printf '1\\n' > "$TEST_ROOT/nvram";;
  commit) printf 'commit\\n' >> "$TEST_ROOT/nvram-actions";;
  *) exit 1;;
esac
""",
        }
        for name, content in fixtures.items():
            path = commands / name
            path.write_text(content)
            path.chmod(0o700)
        replay = source.replace(
            "export PATH=/usr/sbin:/usr/bin:/sbin:/bin",
            "export PATH=" + shlex.quote(str(commands)) + ":/usr/bin:/bin",
        ).replace("MARKER=/tmp/rd03v2-ssh-ready", "MARKER=" + shlex.quote(str(marker)))
        replay = replay.replace("SCRIPT=/etc/init.d/dropbear", "SCRIPT=" + shlex.quote(str(init)))
        patch = root / "persisted-patch.sh"
        patch.write_text(replay)
        environment = dict(os.environ, TEST_ROOT=str(root))

        def reset_ram():
            init.write_text(original_init)
            init.chmod(0o700)
            for path in (marker, running):
                if path.exists():
                    path.unlink()

        def invoke():
            return subprocess.run(["sh", str(patch)], env=environment,
                                  capture_output=True, text=True, timeout=15)

        reset_ram()
        first = invoke()
        assert first.returncode == 0, first.stderr
        assert state.read_text().strip() == "1" and marker.exists() and running.exists()
        assert '"ssh_enabled"' in init.read_text()
        print("PASS first repair: flag, release check, service and ready marker")

        before = actions.read_text()
        assert invoke().returncode == 0
        assert actions.read_text() == before
        print("PASS healthy service: repeated cron run does not restart SSH")

        reset_ram()
        assert invoke().returncode == 0 and marker.exists() and running.exists()
        assert actions.read_text().count("restart") == 2
        print("PASS simulated reboot: restored stock init script is patched again")

        reset_ram()
        (root / "fail").write_text("1")
        failure = invoke()
        assert failure.returncode == 6 and not marker.exists()
        print("PASS startup failure: no false ready marker")


if __name__ == "__main__":
    main()
