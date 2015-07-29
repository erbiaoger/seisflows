import os

import numpy as np
import scipy.signal as _signal
import scipy.interpolate as _interp


def angle(g,p):
    gp = np.dot(g,p)
    gg = np.dot(g,g)
    pp = np.dot(p,p)
    return np.arccos(gp/(gg*pp)**0.5)


def nabla(Z, order=1):
    """ Returns sum of n-th order spatial derivatives of a function defined on
        a 2D rectangular grid; generalizes Laplacian
    """
    if order == 1:
      Zx = Z[:,1:]-Z[:,:-1]
      Zy = Z[1:,:]-Z[:-1,:]
    else:
      raise NotImplementedError

    Z[:,:] = 0.
    Z[:,1:] += Zx
    Z[1:,:] += Zy

    Z[:,-1] = Zx[:,-1]
    Z[-1,:] = Zy[-1,:]
    Z[-1,-1] = (Zx[-1,-1] + Zx[-1,-1])/2.

    return Z


def gauss2(X, Y, mu, sigma):
    """ Evaluates Gaussian over points of X,Y
    """
    # evaluates Gaussian over X,Y
    D = sigma[0, 0]*sigma[1, 1] - sigma[0, 1]*sigma[1, 0]
    B = np.linalg.inv(sigma)
    X = X - mu[0]
    Y = Y - mu[1]
    Z = B[0, 0]*X**2. + B[0, 1]*X*Y + B[1, 0]*X*Y + B[1, 1]*Y**2.
    Z = np.exp(-0.5*Z)
    Z *= (2.*np.pi*np.sqrt(D))**(-1.)
    return Z


def backtrack2(f0, g0, x1, f1, b1=0.1, b2=0.5):
    """ Safeguarded parabolic backtrack
    """
    # parabolic backtrack
    x2 = -g0*x1**2/(2*(f1-f0-g0*x1))

    # apply safeguards
    if x2 > b2*x1:
        x2 = b2*x1
    elif x2 < b1*x1:
        x2 = b1*x1
    return x2


def backtrack3(f0, g0, x1, f1, x2, f2):
    """ Safeguarded cubic backtrack
    """
    raise NotImplementedError


def polyfit2(x, f):
    # parabolic fit
    i = np.argmin(f)
    p = np.polyfit(x[i-1:i+2], f[i-1:i+2], 2)

    if p[0] > 0:
        return -p[1]/(2*p[0])
    else:
        print -1
        raise Exception()


def lsq2(x, f):
    # parabolic least squares fit
    p = np.polyfit(x, f, 2)
    if p[0] > 0:
        return -p[1]/(2*p[0])
    else:
        print -1
        raise Exception()

