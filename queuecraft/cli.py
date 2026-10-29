"""Bounded local CLI. Outputs are exclusive, replayable artifact folders."""
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from . import __version__
from .policies import POLICIES
from .sdk import Intent, Scenario, events_from_csv, run


def read_input(path):
    path=Path(path)
    if path.stat().st_size>64*1024**2:
        raise ValueError("input exceeds64MiB")
    return path.read_text(encoding="ascii")


def main(argv=None):
    parser=argparse.ArgumentParser(prog="queuecraft",description="Exact execution research from recorded books. No live orders.")
    parser.add_argument("--version",action="version",version=__version__)
    commands=parser.add_subparsers(dest="command",required=True)
    p=commands.add_parser("validate",help="validate all events and reconstruct the full book")
    p.add_argument("input",type=Path)
    p=commands.add_parser("replay",help="export every recorded level after every event")
    p.add_argument("input",type=Path);p.add_argument("--out",type=Path,required=True)
    p=commands.add_parser("simulate",help="compute a fresh order and export its complete trace")
    p.add_argument("input",type=Path);p.add_argument("--out",type=Path,required=True)
    p.add_argument("--size",type=int,default=25);p.add_argument("--side",choices=("buy","sell"),default="buy")
    p.add_argument("--policy",choices=POLICIES,default="immediate");p.add_argument("--deadline",type=int,default=5,help="deadline seconds")
    p.add_argument("--latency-ms",type=int,default=0);p.add_argument("--observation-ms",type=int,default=0);p.add_argument("--ack-ms",type=int,default=0)
    p.add_argument("--fee-ppm",type=int,default=0);p.add_argument("--liquidity-ppm",type=int,default=1_000_000)
    p.add_argument("--penalty-ticks",type=int,default=10);p.add_argument("--tie",choices=("recorded_first","arrival_first"),default="recorded_first")
    p=commands.add_parser("study",help="execute an already registered chronological study")
    p.add_argument("sessions",type=Path);p.add_argument("--plan",type=Path,required=True);p.add_argument("--out",type=Path,required=True)
    p=commands.add_parser("verify",help="independently reconcile and rerun an exported order")
    p.add_argument("directory",type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=="study":
            from .study import study
            from .report import study_report
            report=study(args.sessions,args.plan,args.out)
            (args.out/"report.html").write_text(study_report(report))
            print(json.dumps({"executed":report["executed"],"attempts":report["attempts"],"report":str(args.out/"report.html")}))
            return 0
        if args.command=="verify":
            from .reconcile import reconcile
            root=args.directory
            saved=json.loads((root/"result.json").read_text())
            config=json.loads((root/"config.json").read_text())
            data=read_input(root/"input.csv")
            if hashlib.sha256(data.encode()).hexdigest()!=config["input_sha256"]:
                raise ValueError("input hash differs from export")
            result=run(events_from_csv(data),Intent(**config["intent"]),POLICIES[config["policy"]](),Scenario(**config["scenario"]),trace_books=True)
            if result.as_dict()!=saved:
                raise ValueError("fresh replay differs from saved trace")
            sql=reconcile(result)
            if sql["violations"]:raise ValueError(sql)
            print(json.dumps({"replay":"exact","sql":sql}));return 0
        data=read_input(args.input)
        from . import _native
        if args.command=="validate":
            print(json.dumps({"events":_native.validate(data),"sha256":hashlib.sha256(data.encode()).hexdigest()}));return 0
        if args.command=="replay":
            trace=_native.replay(data)
            with args.out.open("x") as output:output.write(trace)
            print(json.dumps({"out":str(args.out),"sha256":hashlib.sha256(trace.encode()).hexdigest()}));return 0
        from .reconcile import reconcile
        from .report import simulation_report
        events=events_from_csv(data)
        first=next(e for e in events if e.kind=="S")
        intent=Intent(args.side,args.size,first.receive_ns,first.receive_ns+args.deadline*1_000_000_000,penalty_ticks=args.penalty_ticks,max_quantity=10_000)
        if events[-1].receive_ns<intent.deadline_ns:
            raise ValueError("input coverage ends before requested deadline")
        scenario=Scenario(latency_ns=args.latency_ms*1_000_000,observation_delay_ns=args.observation_ms*1_000_000,ack_delay_ns=args.ack_ms*1_000_000,fee_ppm=args.fee_ppm,liquidity_ppm=args.liquidity_ppm,tie=args.tie)
        result=run(events,intent,POLICIES[args.policy](),scenario,trace_books=True)
        sql=reconcile(result)
        if sql["violations"]:raise ValueError(sql)
        args.out.mkdir(parents=True,exist_ok=False)
        (args.out/"input.csv").write_text(data)
        (args.out/"config.json").write_text(json.dumps({"schema_version":1,"input_sha256":hashlib.sha256(data.encode()).hexdigest(),"intent":asdict(intent),"scenario":asdict(scenario),"policy":args.policy},indent=2)+"\n")
        (args.out/"result.json").write_text(json.dumps(result.as_dict(),indent=2)+"\n")
        (args.out/"sql.json").write_text(json.dumps(sql,indent=2)+"\n")
        (args.out/"report.html").write_text(simulation_report(result,sql))
        print(json.dumps({"filled":result.filled,"unfilled":result.unfilled,"shortfall2":result.shortfall2,"out":str(args.out)}))
        return 0
    except (ValueError,OverflowError,OSError,StopIteration,ImportError) as error:
        parser.exit(2,f"queuecraft: {error}\n")


if __name__=="__main__":
    sys.exit(main())
