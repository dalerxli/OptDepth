import scipy.optimize as op
import numpy as np
import emcee
import matplotlib.pyplot as plt

from getdist import plots, MCSamples
from astroML.plotting.mcmc import convert_to_stdev


## LIKELIHOOD DEFINATIONS
# Model with constant LSS variance across redshift
def lnlike1(theta, xi, yi, ei):
	f0, t0, gamma, lss_sigma = theta
	# Constant prior on tau_0 in log-space
	if 0 <= f0 < 3 and -11 <= t0 < -2 and 1 <= gamma < 7 and 0 < lss_sigma < 0.6:
		model = f0 * np.exp(-np.exp(t0) * (1 + xi) ** gamma)
		return -0.5 * np.sum((yi - model) ** 2 / (ei ** 2 + lss_sigma ** 2) + np.log(ei ** 2 + lss_sigma ** 2), 0)
	return -np.inf

# Model with LSS variance parameterized by a power law as a function of redshift
def lnlike2(theta, xi, yi, yivar):
	f0, t0, gamma = theta
	# Model for transmission
	model = f0 * np.exp(-t0 * (1 + xi) ** gamma)
	return -0.5 * np.sum((yi - model) ** 2 * yivar)


# Helper function for minimization using op.minimize
nll1 = lambda *args: -lnlike1(*args)
nll2 = lambda *args: -lnlike2(*args)
zline = np.linspace(2.2, 4.2, 100)

# Initial guess
guess1 = [1.5, -6, 4, 0.1]
guess2 = [1.5, 0.0017, 3.8, 0.1, 0]

# Configure GetDist
names = ["f0", "t0", "gamma", "sigma"]
labels = ["f_0", r"\tau_0", "\gamma", "\sigma"]

# Create a grid - delegate this to the inputs of this function
D = np.array([[-0.85627484,  0.51652047],
						[ 0.51652047,  0.85627484]])
x0, x1 = np.mgrid[-3:6:200j, -0.25:0.25:200j]

origPos = np.vstack([x0.ravel(), x1.ravel()])
modPos = np.dot(np.linalg.inv(D), origPos).T + np.array([-5.0625, 3.145])


def mcmcSkewer(bundleObj, logdef=1, niter=2500, do_mcmc=True, plotit=False, return_sampler=False, triangle=False, evalgrid=True, visualize=False, VERBOSITY=False, seed=None):
	"""
	Script to fit simple flux model on each restframe wavelength skewer

	Parameters:
		bundleObj: A list of [z, f, ivar] with the skewer_index 
		logdef: Which model to use (lnlike1: constant variance, lnlike2: power-law variance)
		niter: The number of iterations to run the mcmc (500 for burn-in fixed)
		do_mcmc: Flag whether to perform mcmc
		plotit: Plot the data along with best fit from scipy and mcmc
		return_sampler: Whether to return the raw sampler results without flatchaining
		triangle: Display triangle plot of the parameters
		evalgrid: Whether to compute loglikelihood on a specified grid

	Returns:
		mcmc_chains if return_sampler, else None
	"""
	print('Carrying analysis for skewer', bundleObj[1])
	z, f, ivar = bundleObj[0].T

	ind = ivar > 0
	z, f, sigma = z[ind], f[ind], 1.0 / np.sqrt(ivar[ind])


	if logdef == 1:
		# Try to fit with scipy optimize routine
		opR = op.minimize(nll1, guess1, args=(z, f, sigma), method='Nelder-mead')
		if VERBOSITY:
			print('Scipy optimize results:')
			print('Success =',  result['success'] , 'parameters =', result['x'], '\n')

		if plotit:
			fig, ax1 = plt.subplots(1)
			ax1.errorbar(z, f, sigma, fmt='o', color='gray')
			ax1.plot(zline, opR['x'][0] * np.exp(-np.exp(opR['x'][1]) * (1 + zline) ** opR['x'][2]), '-r')

		if do_mcmc:
			# fix the seed for deterministic behaviour
			np.random.seed(seed)
			nwalkers, ndim = 100, 4
			p0 = [guess1 + 1e-4 * np.random.randn(ndim) for i in range(nwalkers)]

			# configure the sampler
			sampler = emcee.EnsembleSampler(nwalkers, ndim, lnlike1, args=(z, f, sigma))

			# burn-in time - Is this enough?
			p0,_,_ = sampler.run_mcmc(p0, 500);
			sampler.reset()

			sampler.run_mcmc(p0, niter);
			print("Burn-in and Sampling completed \n")

			if return_sampler:
				return sampler.chain
			else:
				# pruning 40 percent of the samples as extra burn-in
				lInd = int(niter * 0.4)
				samps = sampler.chain[:, lInd:, :].reshape((-1, ndim))

				# using percentiles as confidence intervals
				CenVal = np.median(samps, axis=0)
				estimates = list(map(lambda v: (v[1], v[2]-v[1], v[1]-v[0]), zip(*np.percentile(samps, [16, 50, 84], axis=0))))

				if VERBOSITY:
					for count, ele in enumerate(names):
						print(ele + ' = %.3f^{%.3f}_{%.3f}' %(estimates[count][0], estimates[count][1], estimates[count][2]))

				if plotit:
					ax1.plot(zline, CenVal[0] * np.exp(-np.exp(CenVal[1]) * (1 + zline) ** CenVal[2]), '-g')

				# instantiate a getdist object 
				MC = MCSamples(samples=samps, names=names, labels=labels, \
					             ranges={'f0':(0, 3), 't0':(-11, -2), 'gamma':(1, 7), 'lss_sigma':(0, 0.6)})

				# MODIFY THIS TO BE PRETTIER
				if triangle:
					g = plots.getSubplotPlotter()
					g.triangle_plot(MC)

				# Evaluate the pdf on a rotated grid for better estimation
				if evalgrid:
					print('Evaluating on the grid specified \n')
					pdist = MC.get2DDensity('t0', 'gamma')

					# Evalaute density on a grid
					pgrid = np.array([pdist.Prob(*ele) for ele in modPos])
					# Prune to remove negative densities
					pgrid[pgrid < 0] = 0

					# Convert to logLikelihood
					logP = np.log(pgrid)
					logP -= logP.max()
					logP = logP.reshape(x0.shape)

					# Visualize
					if visualize:
						fig, ax2 = plt.subplots(1, figsize=(5,5))
						ax2.contour(x0, x1, convert_to_stdev(logP), levels=[0.683, 0.955, ], colors='k')
						ax2.set_xlabel(r'$x_0$')
						ax2.set_ylabel(r'$x_1$')
						plt.show()

					# fileName1: the log-probability evaluated in the tilted grid
					fileName1 = 'gridlnlike_' + str(bundleObj[1]) + '.dat'
					np.savetxt(fileName1, logP)
					# fileName2: the estimates of f0, ln_t0, gamma, and sigma from MCMC 
					fileName2 = 'estimates_' + str(bundleObj[1]) + '.dat'
					np.savetxt(fileName2, estimates)
					# fileName3: the parameters of 2D gaussian fit to ln_t0-gamma plane
					fileName3 = 'fitparams_' + str(bundleObj[1]) + '.dat'
					fitparams = list(np.mean(samps[:, 1:3], 0)) + \
					                list(np.cov(samps[:, 1:3].T).flat)
					np.savetxt(fileName3, fitparams)


def gauss_like(theta, X, C):
	# define the log-likelihood of the data
	loc, a, b, c = theta[0:2], np.exp(theta[2]), np.exp(theta[3]), np.exp(theta[4])
	modC = C + np.array([[a, b],[b, c]])
	temp = [np.dot(loc - X[i], np.dot(inv(modC[i]), loc - X[i])) + np.log(det(modC[i])) for i in range(len(X))]
	foo = -0.5 * np.sum(temp, 0)
	return foo


def addLogs(fname, npix=200, s_list=None, getsys=False):
	"""Plot the log-likelihood surface for each skewer
	Input: 
	    fname: the path to the folder containing the files

	Returns:
	    None
	    """
	import os
	import time
	import traceback
	import subprocess

	if not os.path.exists(fname):
		print('Oops! There is no such folder')
		return None
	
	currdir = os.getcwd()
	os.chdir(fname)

	try:
		process = subprocess.Popen('ls gridlnlike* > grid.dat', shell=True, stdout=subprocess.PIPE)
		time.sleep(3)
		process = subprocess.Popen('ls fitparams* > params.dat', shell=True, stdout=subprocess.PIPE)
		time.sleep(3)

		# get the name of the files to load
		log_names = np.genfromtxt('grid.dat', dtype=str)
		param_names = np.genfromtxt('params.dat', dtype=str)

		# instantiate containers to hold the data
		Ls = np.empty((len(log_names), npix, npix))
		Ps = np.empty((len(log_names), 6))

		suffix = []
		for i in range(len(Ls)):
			Ls[i] = np.loadtxt(log_names[i])
			Ps[i] = np.loadtxt(param_names[i])
			temp = str.split(ele, '_')
			suffix.append(int(temp[1][:-4]))

		if s_list is not None:
			ind = [i for i, ele in enumerate(suffix) if ele in s_list]
			Ls, Ps = Ls[ind], Ps[ind]
			suffix = suffix[ind]

		# sort for visualization
		Ls = [ele for _,ele in sorted(zip(suffix, Ls))]
		Ps = [ele for _,ele in sorted(zip(suffix, Ps))]
		suffix.sort()

		# joint pdf
		j_pdf = np.sum(Ls, 0)

		colormap = plt.cm.rainbow 
		colors = [colormap(i) for i in np.linspace(0, 1,len(suffix))]

		fig, ax = plt.subplots(1, figsize=(5, 5))
		for i in range(len(suffix)):
			CS = ax.contour(x0, x1, convert_to_stdev(K[i]), levels=[0.683, ], linewidths=0.8, colors=(colors[i],))
			CS.collections[0].set_label(suffix[i])
		ax.contour(x0, x1, convert_to_stdev(j_pdf), levels=[0.683, 0.95], alpha=0.5, colors='k', linestyles='--')
		plt.legend(loc = 'upper center', ncol=6)
		plt.xlabel('x0')
		plt.ylabel('x1')
		plt.show()

		if getsys:
			# means and covariance of all the skewers
			X = Ps[:, 0:2]
			covMat = Ps[:, 2:].reshape(-1, 2, 2)

			nll = lambda *args: -gauss_like(*args)
			res = op.minimize(nll, [-6, 4, 0, 0, 0], args=(X, covMat))

	except:
		traceback.print_exc()
		os.chdir(currdir)

	os.chdir(currdir)


