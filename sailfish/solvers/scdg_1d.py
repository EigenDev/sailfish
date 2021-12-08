"""
An n-th order discontinuous Galerkin solver for 1D scalar advection.
"""

from typing import NamedTuple
from numpy.polynomial.legendre import leggauss, Legendre
from sailfish.mesh import PlanarCartesianMesh
from sailfish.solver import SolverBase


class CellData:
    """
    Gauss weights, quadrature points, and tabulated Legendre polonomials.

    This class works for n-th order Gaussian quadrature in 1D.
    """

    def __init__(self, order=1):
        import numpy as np

        if order <= 0:
            raise ValueError("cell order must be at least 1")

        def leg(x, n, m=0):
            c = [(2 * n + 1) ** 0.5 if i is n else 0.0 for i in range(n + 1)]
            return Legendre(c).deriv(m)(x)

        f = [-1.0, 1.0]  # xsi-coordinate of faces
        g, w = leggauss(order)
        self.gauss_points = g
        self.weights = w
        self.phi_faces = np.array([[leg(x, n, m=0) for n in range(order)] for x in f])
        self.phi_value = np.array([[leg(x, n, m=0) for n in range(order)] for x in g])
        self.phi_deriv = np.array([[leg(x, n, m=1) for n in range(order)] for x in g])
        self.order = order

    def to_weights(self, ux):
        w = self.weights
        p = self.phi_value
        o = self.order
        return [sum(ux[j] * p[j][n] * w[j] for j in range(o)) * 0.5 for n in range(o)]

    def sample(self, uw, j):
        return dot(uw, self.phi_value[j])

    @property
    def num_points(self):
        return self.order


def dot(u, p):
    return sum(u[i] * p[i] for i in range(u.shape[0]))


def update(wavespeed, uw, cell, dx, dt):
    def flux(ux):
        return wavespeed * ux

    nz = uw.shape[0]
    pv = cell.phi_value
    pf = cell.phi_faces
    pd = cell.phi_deriv
    w = cell.weights
    h = [-1.0, 1.0]

    for i in range(nz):
        im1 = (i - 1 + nz) % nz
        ip1 = (i + 1 + nz) % nz

        # surface fluxes
        fimh_l = flux(dot(uw[im1], pf[1]))
        fimh_r = flux(dot(uw[i], pf[0]))
        fiph_l = flux(dot(uw[i], pf[1]))
        fiph_r = flux(dot(uw[ip1], pf[0]))

        if wavespeed > 0.0:
            fimh = fimh_l
            fiph = fiph_l
        else:
            fimh = fimh_r
            fiph = fiph_r

        fs = [fimh, fiph]
        ux = [cell.sample(uw[i], j) for j in range(cell.order)]
        fx = [flux(u) for u in ux]

        for n in range(cell.order):
            udot_s = -sum(fs[j] * pf[j][n] * h[j] for j in range(2)) / dx
            udot_v = +sum(fx[j] * pd[j][n] * w[j] for j in range(cell.num_points)) / dx
            uw[i, n] += (udot_s + udot_v) * dt


class Options(NamedTuple):
    order: int = 1


class Physics(NamedTuple):
    wavespeed: float = 1.0


class Solver(SolverBase):
    """
    An n-th order, discontinuous Galerkin solver for 1D scalar advection.
    """

    def __init__(
        self,
        setup=None,
        mesh=None,
        time=0.0,
        solution=None,
        num_patches=1,
        mode="cpu",
        physics=dict(),
        options=dict(),
    ):
        import numpy as np

        if num_patches != 1:
            raise ValueError("only works on one patch")

        if type(mesh) != PlanarCartesianMesh:
            raise ValueError("only the planar cartesian mesh is supported")

        if mode != "cpu":
            raise ValueError("only cpu mode is supported")

        if setup.boundary_condition != "periodic":
            raise ValueError("only periodic boundaries are supported")

        options = Options(**options)
        physics = Physics(**physics)
        cell = CellData(order=options.order)

        if solution is None:
            num_zones = mesh.shape[0]
            xf = mesh.faces(0, num_zones)  # face coordinates
            px = np.zeros([num_zones, cell.num_points, 1])
            ux = np.zeros([num_zones, cell.num_points, 1])
            uw = np.zeros([num_zones, cell.order, 1])
            dx = mesh.dx

            for i in range(num_zones):
                for j in range(cell.num_points):
                    xsi = cell.gauss_points[j]
                    xj = xf[i] + (xsi + 1.0) * 0.5 * dx
                    setup.primitive(time, xj, px[i, j])

            ux[...] = px[...]  # the conserved variable is also the primitive

            for i in range(num_zones):
                uw[i] = cell.to_weights(ux[i])
            self.conserved_w = uw
        else:
            self.conserved_w = solution

        self.t = time
        self.mesh = mesh
        self.cell = cell
        self._options = options
        self._physics = physics

    @property
    def solution(self):
        return self.conserved_w

    @property
    def primitive(self):
        return self.conserved_w[:, 0]

    @property
    def time(self):
        return self.t

    @property
    def maximum_cfl(self):
        return 0.05

    @property
    def options(self):
        return self._options._asdict()

    @property
    def physics(self):
        return self._physics._asdict()

    def advance(self, dt):
        update(self._physics.wavespeed, self.conserved_w, self.cell, self.mesh.dx, dt)
        self.t += dt
