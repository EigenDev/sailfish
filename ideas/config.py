from typing import Literal, Union
from schema import schema
from geometry import CoordinateBox
from models import InitialData, Shocktube


@schema
class Report:
    cadence: int = 100


@schema
class Checkpoint:
    cadence: float = 1.0
    format: Literal["none", "pickle"] = "pickle"


@schema
class Diagnostic:
    name: str


@schema
class Timeseries:
    cadence: float = 1.0
    diagnostics: list[Diagnostic] = None


@schema
class Driver:
    """
    Deals with the simulation control flow and input/output

    The simulation driver takes care of setting problem initial data,
    constructing solver instances, recording timeseries data (on-the-fly
    science products), and writing checkpoint files.

    Fields
    ------

    tstart: time when the simulation starts (does not need to be t=0)
    tfinal: time when the simulation ends
    report: number of iterations between one-line report messages
    timeseries: high-cadence recording of science products
    """

    tstart: float = 0.0
    tfinal: float = 1.0
    report: Report = Report()
    checkpoint: Checkpoint = Checkpoint()
    timeseries: Timeseries = Timeseries()
    cfl_number: Union[float, Literal["auto"]] = "auto"


@schema
class GammaLawEOS:
    """
    Adiabatic EOS with given gamma-law index
    """

    gamma_law_index: float = 5.0 / 3.0


@schema
class IsothermalEOS:
    """
    Isothermal EOS with a uniform sound speed
    """

    sound_speed: float = 1.0


@schema
class LocallyIsothermalEOS:
    """
    Isothermal EOS with a uniform nominal Mach number
    """

    mach_number: float = 10.0


EquationOfState = Union[GammaLawEOS, IsothermalEOS, LocallyIsothermalEOS]


@schema
class Physics:
    equation_of_state: EquationOfState = GammaLawEOS()


Reconstruction = Union[Literal["pcm"], tuple[Literal["plm"], float]]
TimeIntegration = Literal["fwd", "rk1", "rk2", "rk3"]


@schema
class Scheme:
    """
    Algorithm parameters for the solution scheme

    A scheme refers to the parts of a solver that affect the numerical
    solution up to the truncation order.

    Fields
    ------

    reconstruction:    spatial reconstruction method
    time_integration:  time-integration scheme (fwd|rk1|rk2|rk3)
    """

    reconstruction: Reconstruction = "pcm"
    time_integration: TimeIntegration = "fwd"


@schema
class Strategy:
    """
    Algorithm parameters only affecting performance

    With everything else held fixed, differences in the solver strategy should
    only affect how fast the code runs, and not the numerical solution it
    generates.

    Fields
    ------

    hardware:    compute device [cpu|gpu]
    data_layout: array-of-struct (fields-last) or struct-of-array (fields-first)
    cache_flux:  one Riemann problem per face, difference the resulting array
    cache_prim:  pre-compute primitive quantities, vs. re-compute over stencil
    num_patches: decompose domain to enable threads, streams, or multiple GPU's
    num_threads: use a thread pool of this size to drive a multi-patch solver
    gpu_streams: use the per-thread-default-stream, or one stream per grid patch
    """

    hardware: Literal["cpu", "gpu"] = "cpu"
    data_layout: Literal["fields-first", "fields-last"] = "fields-last"
    cache_flux: bool = False
    cache_prim: bool = False
    cache_grad: bool = False
    num_patches: int = 1
    num_threads: int = 1
    gpu_streams: Literal["per-thread", "per-patch"] = "per-thread"

    @property
    def transpose(self):
        """
        synonym for fields-first (also called struct-of-arrays) data layout
        """
        return self.data_layout == "fields-first"


@schema
class Sailfish:
    """
    Top-level application configuration struct

    Fields
    ------

    name:      a name given to the run
    driver:    runs the simulation main loop, handles IO
    physics:   the physics equations to be solved
    domain:    the physical domain of the problem
    strategy:  the solution strategy; does not affect the numerical solution
    scheme:    algorithmic choices which can affect the solution accuracy
    """

    name: str = None
    driver: Driver = Driver()
    initial_data: InitialData = Shocktube()
    physics: Physics = Physics()
    domain: CoordinateBox = CoordinateBox()
    strategy: Strategy = Strategy()
    scheme: Scheme = Scheme()


def parse_num_zones(arg):
    """
    Promote an integer or two-tuple to a three-tuple of integers

    This factory function is used by the argparse type parameter to convert
    user input to a domain.num_zones parameter.
    """
    res = tuple(int(i) for i in arg.split(","))

    if len(res) == 1:
        return res + (1, 1)
    if len(res) == 2:
        return res + (1,)
    if len(res) == 3:
        return res
    raise ValueError(f"invalid argument for num_zones {arg}")


def parse_reconstruction(arg):
    """
    Promote a string to a reconstruction model

    This factory function is used by the argparse type parameter to convert
    user input to a scheme.reconstruction parameter.
    """
    try:
        mode, theta = arg.split(":")
        return mode, float(theta)
    except ValueError:
        if arg == "plm":
            return arg, 1.5
        else:
            return arg


def add_config_arguments(parser: "argparser.ArgumentParser"):
    """
    Add arguments to a parser controlling a subset of a Sailfish config struct
    """

    parser.add_argument(
        "--mode",
        "--hardware",
        dest="strategy.hardware",
        choices=Strategy.type_args("hardware"),
        help="execution mode",
    )
    parser.add_argument(
        "-n",
        "--num-zones",
        "--resolution",
        type=parse_num_zones,
        dest="domain.num_zones",
        metavar="N",
    )
    parser.add_argument(
        "--patches",
        type=int,
        default=None,
        metavar="P",
        help=Strategy.describe("num_patches"),
        dest="strategy.num_patches",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        metavar="T",
        help=Strategy.describe("num_threads"),
        dest="strategy.num_threads",
    )
    parser.add_argument(
        "--streams",
        type=str,
        choices=Strategy.type_args("gpu_streams"),
        metavar="S",
        help=Strategy.describe("gpu_streams"),
        dest="strategy.gpu_streams",
    )
    parser.add_argument(
        "-m",
        "--time-integration",
        choices=Scheme.type_args("time_integration"),
        help=Scheme.describe("time_integration"),
        dest="scheme.time_integration",
    )
    parser.add_argument(
        "-r",
        "--reconstruction",
        type=parse_reconstruction,
        help=Scheme.describe("reconstruction"),
        dest="scheme.reconstruction",
        metavar="R",
    )
    parser.add_argument(
        "-e",
        "--tfinal",
        type=float,
        help=Driver.describe("tfinal"),
        dest="driver.tfinal",
        metavar="T",
    )
    parser.add_argument(
        "-f",
        "--fold",
        "--report-cadence",
        type=int,
        help=Report.describe("cadence"),
        dest="driver.report.cadence",
        metavar="F",
    )
    parser.add_argument(
        "--checkpoint",
        "-c",
        type=float,
        dest="driver.checkpoint.cadence",
        metavar="C",
    )
    parser.add_argument(
        "--timeseries",
        "-t",
        type=float,
        dest="driver.timeseries.cadence",
        metavar="T",
    )
    parser.add_argument(
        "--data-layout",
        type=str,
        choices=Strategy.type_args("data_layout"),
        help=Strategy.describe("data_layout"),
        dest="strategy.data_layout",
    )
    parser.add_argument(
        "--cache-prim",
        action="store_true",
        dest="strategy.cache_prim",
        default=None,
    )
    parser.add_argument(
        "--cache-flux",
        action="store_true",
        dest="strategy.cache_flux",
        default=None,
    )
    parser.add_argument(
        "--cache-grad",
        action="store_true",
        dest="strategy.cache_grad",
        default=None,
    )


if __name__ == "__main__":
    from rich.console import Console
    from rich.live import Live

    console = Console()
    config = Sailfish(physics=Physics(equation_of_state=IsothermalEOS()))

    for field in config.__dataclass_fields__:
        value = getattr(config, field)
        if hasattr(value, "__configmodel__"):
            console.print()
            console.print(value)