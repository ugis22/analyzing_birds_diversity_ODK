"""Firth (1993) bias reduced logistic regression.

Wood & Kahl (2024) fit a plain binomial GLM of outcome on logit(confidence).
With small validation sets the plain estimate does not exist when the
outcome is perfectly separated, for example when every validated clip is
correct. Firth's penalty, 0.5 * log|I(beta)|, always gives finite estimates
and is close to the GLM when the data are informative.
"""

from dataclasses import dataclass

import numpy as np
from scipy.special import expit


@dataclass
class FirthResult:
    """Result of a Firth logistic regression fit.

    Attributes:
        coef: Coefficients, intercept first.
        cov: Inverse Fisher information at the estimate.
        loglik: Log likelihood without the penalty.
        penalized_loglik: Log likelihood with the Firth penalty.
        n_iter: Number of iterations run.
        converged: Whether the step size fell below the tolerance.

    """

    coef: np.ndarray
    cov: np.ndarray
    loglik: float
    penalized_loglik: float
    n_iter: int
    converged: bool

    def predict(self, design: np.ndarray) -> np.ndarray:
        """Return the fitted probability for each row of the design."""
        return expit(design @ self.coef)


def _penalized_loglik(design, y, beta):
    """Return the plain and the penalized log likelihood at `beta`."""
    eta = design @ beta
    p = expit(eta)
    ll = float(np.sum(y * eta - np.logaddexp(0.0, eta)))
    w = p * (1 - p)
    _, logdet = np.linalg.slogdet(design.T @ (design * w[:, None]))
    return ll, ll + 0.5 * logdet


def firth_logit(
    design: np.ndarray,
    y: np.ndarray,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> FirthResult:
    """Fit a Firth logistic regression by Newton steps.

    design must include an intercept column. y holds 0 or 1 outcomes.
    """
    design = np.asarray(design, dtype=float)
    y = np.asarray(y, dtype=float)
    beta = np.zeros(design.shape[1])
    _, pll = _penalized_loglik(design, y, beta)
    converged = False
    n_iter = 0
    while n_iter < max_iter:
        n_iter += 1
        p = expit(design @ beta)
        w = p * (1 - p)
        info = design.T @ (design * w[:, None])
        info_inv = np.linalg.inv(info)

        # Diagonal of the weighted hat matrix. Firth's correction adds
        # these leverages to the score.
        h = np.einsum("ij,jk,ik->i", design, info_inv, design) * w
        score = design.T @ (y - p + h * (0.5 - p))
        step = info_inv @ score

        # Halve the step until the penalized likelihood stops falling.
        for _ in range(30):
            new_beta = beta + step
            _, new_pll = _penalized_loglik(design, y, new_beta)
            if new_pll >= pll - 1e-12:
                break
            step = step / 2
        beta, pll = new_beta, new_pll
        if np.max(np.abs(step)) < tol:
            converged = True
            break

    p = expit(design @ beta)
    w = p * (1 - p)
    cov = np.linalg.inv(design.T @ (design * w[:, None]))
    ll, pll = _penalized_loglik(design, y, beta)
    return FirthResult(beta, cov, ll, pll, n_iter, converged)
