from numpy.typing import NDArray
from .kernels import device


static = R"""
#define min2(a, b) ((a) < (b) ? (a) : (b))
#define max2(a, b) ((a) > (b) ? (a) : (b))
#define min3(a, b, c) min2(a, min2(b, c))
#define max3(a, b, c) max2(a, max2(b, c))

#if NPRIM == 3
#define NCONS 3
#define NVECS 1
#define RHO 0
#define UXX 1
#define PRE 2
#define DEN 0
#define SXX 1
#define NRG 2
#elif NPRIM == 4
#define NCONS 4
#define NVECS 2
#define RHO 0
#define UXX 1
#define UYY 2
#define PRE 3
#define DEN 0
#define SXX 1
#define SYY 2
#define NRG 3
#elif NPRIM == 5
#define NCONS 5
#define NVECS 3
#define RHO 0
#define UXX 1
#define UYY 2
#define UZZ 3
#define PRE 4
#define DEN 0
#define SXX 1
#define SYY 2
#define SZZ 3
#define NRG 4
#else
#error("NPRIM must be 3, 4, or 5")
#endif

#ifndef GAMMA_LAW_INDEX
#define GAMMA_LAW_INDEX (5.0 / 3.0)
#endif
"""


@device(static=static)
def prim_to_cons(p: NDArray[float], u: NDArray[float]):
    R"""
    DEVICE void prim_to_cons(double *p, double *u)
    {
        #if NVECS == 1
        double rho = p[RHO];
        double gbx = p[UXX];
        double pre = p[PRE];
        double w =  sqrt(1.0 + gbx * gbx);
        double h = 1.0 + pre / rho * (1.0 + 1.0 / (GAMMA_LAW_INDEX - 1.0));
        double m = rho * w;
        u[DEN] = m;
        u[SXX] = m * h * gbx;
        u[NRG] = m * (h * w - 1.0) - pre;

        #elif NVECS == 2
        double rho = p[RHO];
        double gbx = p[UXX];
        double gby = p[UYY];
        double pre = p[PRE];
        double w =  sqrt(1.0 + gbx * gbx + gby * gby);
        double h = 1.0 + pre / rho * (1.0 + 1.0 / (GAMMA_LAW_INDEX - 1.0));
        double m = rho * w;
        u[DEN] = m;
        u[SXX] = m * h * gbx;
        u[SYY] = m * h * gby;
        u[NRG] = m * (h * w - 1.0) - pre;

        #elif NVECS == 3
        double rho = p[RHO];
        double gbx = p[UXX];
        double gby = p[UYY];
        double gbz = p[UZZ];
        double pre = p[PRE];
        double w =  sqrt(1.0 + gbx * gbx + gby * gby + gbz * gbz);
        double h = 1.0 + pre / rho * (1.0 + 1.0 / (GAMMA_LAW_INDEX - 1.0));
        double m = rho * w;
        u[DEN] = m;
        u[SXX] = m * h * gbx;
        u[SYY] = m * h * gby;
        u[SZZ] = m * h * gbz;
        u[NRG] = m * (h * w - 1.0) - pre;
        #endif
    }
    """


@device(static=static)
def cons_to_prim(u: NDArray[float], p: NDArray[float]):
    R"""
    DEVICE void cons_to_prim(double *u, double *p)
    {
        int iteration = 0;
        int newton_iter_max = 50;

        double gm = GAMMA_LAW_INDEX;
        double m = u[DEN];
        double tau = u[NRG];
        double pre = p[PRE];
        double error_tolerance = 1e-12;// * (m + tau);
        double w0;

        #if NVECS == 1
        double ss = u[SXX] * u[SXX];
        #elif NVECS == 2
        double ss = u[SXX] * u[SXX] + u[SYY] * u[SYY];
        #elif NVECS == 3
        double ss = u[SXX] * u[SXX] + u[SYY] * u[SYY] + u[SZZ] * u[SZZ];
        #endif

        while (1)
        {
            double et  = tau + pre + m;
            double b2  = min2(ss / et / et, 1.0 - 1e-10);
            double w2  = 1.0 / (1.0 - b2);
            double w   = sqrt(w2);
            double e   = (tau + m * (1.0 - w) + pre * (1.0 - w2)) / (m * w);
            double rho = m / w;
            double h   = 1.0 + e + pre / rho;
            double a2  = gm * pre / (rho * h);
            double f   = rho * e * (gm - 1.0) - pre;
            double g   = b2 * a2 - 1.0;

            pre -= f / g;

            if (fabs(f) < error_tolerance)
            {
                w0 = w;
                break;
            }
            if (iteration == newton_iter_max)
            {
                printf("c2p failed: %f %f %f\n", u[0], u[1], u[2]);
                exit(1);
            }
            iteration += 1;
        }

        p[RHO] = m / w0;
        p[PRE] = pre;

        #if NVECS >= 1
        p[UXX] = w0 * u[1] / (tau + m + pre);
        #endif
        #if NVECS >= 2
        p[UYY] = w0 * u[2] / (tau + m + pre);
        #endif
        #if NVECS >= 3
        p[UZZ] = w0 * u[3] / (tau + m + pre);
        #endif
    }
    """


@device(static=static, device_funcs=[cons_to_prim])
def cons_to_prim_check(u: NDArray[float], p: NDArray[float]) -> int:
    R"""
    DEVICE int cons_to_prim_check(double *u, double *p)
    {
        cons_to_prim(u, p);

        if (u[DEN] < 0.0) {
            return 1;
        }
        if (u[NRG] < 0.0) {
            return 2;
        }
        if (p[PRE] < 0.0) {
            return 3;
        }
        return 0;
    }
    """


@device(static=static)
def prim_and_cons_to_flux(
    p: NDArray[float],
    u: NDArray[float],
    f: NDArray[float],
    direction: int,
):
    R"""
    DEVICE void prim_and_cons_to_flux(double *p, double *u, double *f, int direction)
    {
        #if NVECS == 1
        double gbx = p[UXX];
        double gby = 0.0;
        double gbz = 0.0;
        double uu = gbx * gbx;
        #elif NVECS == 2
        double gbx = p[UXX];
        double gby = p[UYY];
        double gbz = 0.0;
        double uu = gbx * gbx + gby * gby;
        #elif NVECS == 3
        double gbx = p[UXX];
        double gby = p[UYY];
        double gbz = p[UZZ];
        double uu = gbx * gbx + gby * gby + gbz * gbz;
        #endif

        double pre = p[PRE];
        double vn = 0.0;
        double w = sqrt(1.0 + uu);

        switch (direction)
        {
            case 1: vn = gbx / w; break;
            case 2: vn = gby / w; break;
            case 3: vn = gbz / w; break;
        }

        f[DEN] = vn * u[DEN];
        f[NRG] = vn * u[NRG] + pre * vn;

        #if NVECS >= 1
        f[SXX] = vn * u[SXX] + pre * (direction == 1);
        #endif
        #if NVECS >= 2
        f[SYY] = vn * u[SYY] + pre * (direction == 2);
        #endif
        #if NVECS >= 3
        f[SZZ] = vn * u[SZZ] + pre * (direction == 3);
        #endif
    }
    """


@device(static=static, device_funcs=[prim_and_cons_to_flux])
def prim_to_flux(p: NDArray[float], f: NDArray[float], direction: int):
    R"""
    DEVICE void prim_and_cons_to_flux(double *p, double *f, int direction)
    {
        double u[NCONS];
        prim_to_cons(p, u);
        prim_and_cons_to_flux(p, u, f, direction);
    }
    """


@device(static=static)
def sound_speed_squared(p: NDArray[float]) -> float:
    R"""
    DEVICE double sound_speed_squared(double *p)
    {
        double rho = p[DEN];
        double pre = p[PRE];
        double rhoh = rho + pre * (1.0 + 1.0 / (GAMMA_LAW_INDEX - 1.0));
        return pre / rhoh * GAMMA_LAW_INDEX;
    }
    """


@device(static=static, device_funcs=[sound_speed_squared])
def outer_wavespeeds(
    p: NDArray[float],
    wavespeeds: NDArray[float],
    direction: int,
):
    R"""
    DEVICE void outer_wavespeeds(
        double *p,
        double *wavespeeds,
        int direction)
    {
        #if NVECS == 1
        double gbx = p[UXX];
        double gby = 0.0;
        double gbz = 0.0;
        double uu = gbx * gbx;
        #elif NVECS == 2
        double gbx = p[UXX];
        double gby = p[UYY];
        double gbz = 0.0;
        double uu = gbx * gbx + gby * gby;
        #elif NVECS == 3
        double gbx = p[UXX];
        double gby = p[UYY];
        double gbz = p[UZZ];
        double uu = gbx * gbx + gby * gby + gbz * gbz;
        #endif

        double w = sqrt(1.0 + uu);
        double vn = 0.0;
        double a2 = sound_speed_squared(p);

        switch (direction)
        {
            case 1: vn = gbx / w; break;
            case 2: vn = gby / w; break;
            case 3: vn = gbz / w; break;
        }
        double vv = uu / (1.0 + uu);
        double v2 = vn * vn;
        double k0 = sqrt(a2 * (1.0 - vv) * (1.0 - vv * a2 - v2 * (1.0 - a2)));

        wavespeeds[0] = (vn * (1.0 - a2) - k0) / (1.0 - vv * a2);
        wavespeeds[1] = (vn * (1.0 - a2) + k0) / (1.0 - vv * a2);
    }
    """


@device(
    static=static,
    device_funcs=[
        sound_speed_squared,
        outer_wavespeeds,
    ],
)
def max_wavespeed(p: NDArray[float]) -> float:
    R"""
    DEVICE double max_wavespeed(double *p)
    {
        #if NVECS == 1
        double ai[2];
        outer_wavespeeds(p, ai, 1);
        return max2(fabs(ai[0]), fabs(ai[1]));

        #elif NVECS == 2
        double ai[2];
        double aj[2];
        outer_wavespeeds(p, ai, 1);
        outer_wavespeeds(p, aj, 2);
        return max2(max2(fabs(ai[0]), fabs(ai[1])), max2(fabs(aj[0]), fabs(aj[1])));

        #elif NVECS == 3
        double ai[2];
        double aj[2];
        double ak[2];
        outer_wavespeeds(p, ai, 1);
        outer_wavespeeds(p, aj, 2);
        outer_wavespeeds(p, ak, 3);
        return max3(max2(fabs(ai[0]), fabs(ai[1])), max2(fabs(aj[0]), fabs(aj[1])), max2(fabs(ak[0]), fabs(ak[1])));
        #endif
    }
    """


@device(
    static=static,
    device_funcs=[
        prim_to_cons,
        prim_and_cons_to_flux,
        outer_wavespeeds,
    ],
)
def riemann_hlle(
    pl: NDArray[float],
    pr: NDArray[float],
    flux: NDArray[float],
    direction: int,
):
    R"""
    DEVICE void riemann_hlle(double *pl, double *pr, double *flux, int direction)
    {
        double ul[NCONS];
        double ur[NCONS];
        double fl[NCONS];
        double fr[NCONS];
        double al[2];
        double ar[2];

        prim_to_cons(pl, ul);
        prim_to_cons(pr, ur);
        prim_and_cons_to_flux(pl, ul, fl, direction);
        prim_and_cons_to_flux(pr, ur, fr, direction);
        outer_wavespeeds(pl, al, direction);
        outer_wavespeeds(pr, ar, direction);

        double am = min3(0.0, al[0], ar[0]);
        double ap = max3(0.0, al[1], ar[1]);

        for (int q = 0; q < NCONS; ++q)
        {
            flux[q] = (fl[q] * ap - fr[q] * am - (ul[q] - ur[q]) * ap * am) / (ap - am);
        }
    }
    """


if __name__ == "__main__":
    from numpy import array, zeros_like, allclose
    from kernels import kernel

    nprim = 5

    @kernel(device_funcs=[cons_to_prim], define_macros=dict(NPRIM=nprim))
    def kernel_cons_to_prim(u: NDArray[float], p: NDArray[float], ni: int = None):
        R"""
        KERNEL void kernel_cons_to_prim(double *u, double *p, int ni)
        {
            FOR_EACH_1D(ni)
            {
                cons_to_prim(&u[NCONS * i], &p[NCONS * i]);
            }
        }
        """
        return u.size // nprim, (u, p, u.size // nprim)

    @kernel(device_funcs=[prim_to_cons], define_macros=dict(NPRIM=nprim))
    def kernel_prim_to_cons(p: NDArray[float], u: NDArray[float], ni: int = None):
        R"""
        KERNEL void kernel_prim_to_cons(double *p, double *u, int ni)
        {
            FOR_EACH_1D(ni)
            {
                prim_to_cons(&p[NCONS * i], &u[NCONS * i]);
            }
        }
        """
        return p.size // nprim, (p, u, p.size // nprim)

    if nprim == 3:
        p = array([[1.0, 5.0, 0.01]])
    if nprim == 4:
        p = array([[1.0, 2.0, 5.0, 0.01]])
    if nprim == 5:
        p = array([[1.0, 2.0, 5.0, 1.0, 0.01]])

    u = zeros_like(p)
    q = zeros_like(p)
    kernel_prim_to_cons(p, u)
    kernel_cons_to_prim(u, q)
    assert allclose(p - q, 0.0)
