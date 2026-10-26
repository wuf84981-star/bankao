# ============================================================
# S8 五刀离线单测：每日备份（D50 甲 · 2026-09-11 拍：调度器 04:00 全家福+轮转7份）
# 断言主线：两张全家福各归各名、密码只进 env 不上 argv（argv 会被 ps 看光）；
# 轮转按系列各留 7 份、不碰无关文件；一腿砸不连坐另一腿（try/except 各自兜）；
# 零真执行：runner 假件注入+tmp 目录——测试绝不碰真库真磁盘（烧钱/误删双预防）。
# 直喂 now 可测形状：reminder/clean 同款家规第三次复用。
# ============================================================
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from backend.jobs import run_daily_backup

_URL = "postgresql+psycopg://zhu:pa%40ss@dbhost:5432/bankao"   # 假串：密码含转义 @ 验 unquote


def _fake_runner(fail_first_word: str | None = None):
    """记 calls、按 argv 里的 -f/-czf 目标写出假文件——轮转与产物断言都靠它。"""
    calls: list[tuple[list, dict]] = []

    def runner(argv, **kw):
        calls.append((argv, kw))
        if fail_first_word and argv[0] == fail_first_word:
            raise RuntimeError("假罢工")
        for flag in ("-f", "-czf"):
            if flag in argv:
                Path(argv[argv.index(flag) + 1]).write_bytes(b"xx")
        return SimpleNamespace(returncode=0)
    return runner, calls


def test_two_products_password_stays_in_env(tmp_path):
    """两张全家福按日期命名；pg_dump 用 -Fp 纯文本带 --clean --if-exists——
    演练血案换形：-Fc custom 归档带版本头（1.16），db 箱 pg_restore 16 拒读，
    备份能拍不能复原叫没备份；纯 SQL 跨版本稳。
    密码解自 URL（含 %40 转义）只进 env 的 PGPASSWORD——argv 里一个字都不许出现。"""
    runner, calls = _fake_runner()
    made = run_daily_backup(now=datetime(2026, 9, 11, 4, 0),
                            dir=str(tmp_path), runner=runner, url=_URL)
    assert [p.name for p in made] == ["bankao_2026-09-11.sql",
                                      "uploads_2026-09-11.tar.gz"]
    dump_argv, dump_kw = calls[0]
    assert dump_argv[0] == "pg_dump" and "-Fp" in dump_argv
    assert "--clean" in dump_argv and "--if-exists" in dump_argv
    assert "pa@ss" not in " ".join(dump_argv)          # 命令行零密码
    assert dump_kw["env"]["PGPASSWORD"] == "pa@ss"     # 密码走环境变量的后门
    assert dump_argv[dump_argv.index("-h") + 1] == "dbhost"


def test_rotation_keeps_seven_per_series(tmp_path):
    """已有 9 天旧片+今天新拍=10 份 → 各系列留最新 7（文件名带 ISO 日期，
    字典序即时间序）；被删的是最老的 09-01~09-03。"""
    for d in range(1, 10):   # 2026-09-01 … 09-09
        (tmp_path / f"bankao_2026-09-{d:02d}.sql").write_bytes(b"x")
        (tmp_path / f"uploads_2026-09-{d:02d}.tar.gz").write_bytes(b"x")
    runner, _ = _fake_runner()
    run_daily_backup(now=datetime(2026, 9, 11, 4, 0),
                     dir=str(tmp_path), runner=runner, url=_URL)
    dumps = sorted(p.name for p in tmp_path.glob("bankao_*.sql"))
    assert len(dumps) == 7 and dumps[-1] == "bankao_2026-09-11.sql"
    assert "bankao_2026-09-01.sql" not in dumps
    assert len(list(tmp_path.glob("uploads_*.tar.gz"))) == 7   # 两系列各转各的


def test_rotten_leg_not_linked(tmp_path, capsys):
    """库腿罢工 → uploads 腿照常出品、函数不抛、日志留声——
    一张没拍好不意味着另一张白拍（backup.sh 时代脚本一个 set -e 全断的翻案）。"""
    runner, _ = _fake_runner(fail_first_word="pg_dump")
    made = run_daily_backup(now=datetime(2026, 9, 11, 4, 0),
                            dir=str(tmp_path), runner=runner, url=_URL)
    assert [p.name for p in made] == ["uploads_2026-09-11.tar.gz"]
    assert "库全家福没拍成" in capsys.readouterr().out


def test_rotation_leaves_unrelated_files_alone(tmp_path):
    """外科轮转：只认两个命名系列（bankao_*.sql / uploads_*.tar.gz）——
    readme.txt 与旧格式遗留 bankao_manual.dump（换形前的 .dump 尾巴）都不在
    系列形状内，一个都不许被啃。（本例首版恰被 glob 边界反咬一口：当年系列
    是 *.dump，「局外人」用 .sql 才干净；换形后对调——glob 的边界就是系列的边界。）"""
    (tmp_path / "readme.txt").write_text("别删我")
    (tmp_path / "bankao_manual.dump").write_bytes(b"x")
    for d in range(1, 12):   # 11 张真旧片压顶，逼轮转动手
        (tmp_path / f"bankao_2026-08-{d:02d}.sql").write_bytes(b"x")
    runner, _ = _fake_runner()
    run_daily_backup(now=datetime(2026, 9, 11, 4, 0),
                     dir=str(tmp_path), runner=runner, url=_URL)
    assert (tmp_path / "readme.txt").exists()
    assert (tmp_path / "bankao_manual.dump").exists()
    assert len(list(tmp_path.glob("bankao_2026-*.sql"))) == 7
