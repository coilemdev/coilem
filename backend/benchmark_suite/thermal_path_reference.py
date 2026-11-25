"""Independent audit references: scalar integrations and a cell-centred 2D FV solve.

Never imports production thermal code. The FV stencil discretizes Fourier flux
and boundary half-cell conduction in series with Robin convection. This is a
numerical cross-check, clearly separate from the exact scalar/limit references.
"""

import math


def coil_mean_difference(active_length, end_length, copper_area, conductivity, transfer):
    # On each half, integrate q/(k*A)*(ell^2-x^2)/2 then average.
    # There are four equivalent half-active legs and four half-end arcs per
    # paired aggregate; the total-area convention gives these separate drops.
    active_drop = transfer * active_length / (12 * conductivity * copper_area)
    end_drop = -transfer * end_length / (12 * conductivity * copper_area)
    return active_drop - end_drop


def square_dirichlet_mean_coefficient(terms=400):
    # Integrate the independent sine-series solution on the unit square.
    return 64 / math.pi**6 * sum(1 / (m*m*n*n*(m*m+n*n))
        for m in range(1, 2*terms, 2) for n in range(1, 2*terms, 2))


def square_finite_volume(biot, cells):
    import numpy as np

    # Unit square, k=1, length=1, q=1, ambient=0: Q=1, so mean is R.
    dx, h = 1 / cells, 2 * biot
    face_to_air = dx / (dx / 2 + 1 / h)
    diagonal = np.full(cells, 2.)
    diagonal[0] = diagonal[-1] = 1 + face_to_air
    axis = np.diag(diagonal) - np.diag(np.ones(cells-1), 1) - np.diag(np.ones(cells-1), -1)
    # Solve the separable discrete 2D operator without a new sparse dependency.
    eigenvalues, vectors = np.linalg.eigh(axis)
    projection = vectors.T @ np.ones(cells)
    coefficients = dx*dx * np.outer(projection, projection) / (eigenvalues[:, None] + eigenvalues)
    grid = vectors @ coefficients @ vectors.T
    rejection = face_to_air * (grid[0].sum() + grid[-1].sum() + grid[:, 0].sum() + grid[:, -1].sum())
    return float(grid.mean()), float(rejection)
