from functools import partial
import tensorflow as tf

from bayesflow.computational_utilities import mmd_kernel, gaussian_kernel_matrix


def heteroscedastic_loss(network, params, x):
    """ Computes the heteroscedastic loss between true and predicted parameters. 
    Legacy, used in the paper
    Radev, S. T., Mertens, U. K., Voss, A., & Köthe, U. (2020). Towards end‐to‐end likelihood‐free inference with convolutional neural networks.

    Parameters
    ----------
    network  : tf.keras.Model
        A neural network with a single output vector (posterior means)
    params   : tf.Tensor of shape (batch_size, n_out_dim)
        Data-generating parameters, as sampled from prior
    x        : tf.Tensor of shape (batch_size, N, x_dim)
        Synthetic data sets generated by the parameters

    Returns
    -------
    loss : tf.Tensor
        A single scalar value representing the heteroscedastic loss, shape (,)
    """

    pred_mean, pred_var = network(x)
    logvar = tf.reduce_sum(0.5 * tf.math.log(pred_var), axis=-1)
    squared_error = tf.reduce_sum(0.5 * tf.math.square(params - pred_mean) / pred_var, axis=-1)
    loss = tf.reduce_mean(squared_error + logvar)
    return loss


def kl_latent_space_gaussian(network, *args):
    """ Computes the Kullback-Leibler divergence (Maximum Likelihood Loss) between true and approximate
    posterior using simulated data and parameters. Assumes a Gaussian latyent space.

    Parameters
    ----------
    network   : tf.keras.Model
        A single model amortizer
    *args
        List of arguments as inputs to network (e.g. model_indices, params, sim_data)

    Returns
    -------
    loss : tf.Tensor
        A single scalar value representing the KL loss, shape (,)

    Examples
    --------
    Parameter estimation

    >>> kl_latent_space(net, params, sim_data)

    Model comparison

    >>> kl_latent_space(net, model_indices, sim_data)

    Meta

    >>> kl_latent_space(net, model_indices, params, sim_data)
    """

    z, log_det_J = network(*args)
    loss = tf.reduce_mean(0.5 * tf.square(tf.norm(z, axis=-1)) - log_det_J)
    return loss


def kl_latent_space_student(network, *args):
    """ Computes the Kullback-Leibler divergence (Maximum Likelihood Loss) between true and approximate
    posterior using simulated data and parameters. Assumes a latent student t-Distribution as a source.

    Parameters
    ----------
    network   : tf.keras.Model
        A single model amortizer
    *args
        List of arguments as inputs to network (e.g. model_indices, params, sim_data)

    Returns
    -------
    loss : tf.Tensor
        A single scalar value representing the KL loss, shape (,)
    """
    
    v, z, log_det_J = network(*args)
    d = z.shape[-1]
    loss = 0.
    loss -= d * tf.math.lgamma(0.5*(v + 1))
    loss += d * tf.math.lgamma(0.5*v + 1e-15)
    loss += (0.5*d) * tf.math.log(v + 1e-15)
    loss += 0.5*(v+1) * tf.reduce_sum(tf.math.log1p(z**2 / v), axis=-1)
    loss -= log_det_J
    mean_loss = tf.reduce_mean(loss)
    return mean_loss


def log_loss(network, model_indices, sim_data, kl_weight=0.01):
    """ Computes the logloss given output probs and true model indices m_true.

    Parameters
    ----------
    network       : tf.keras.Model
        An evidential network (with real outputs in ``[1, +inf]``)
    model_indices : tf.Tensor of shape (batch_size, n_models)
        True model indices
    sim_data      : tf.Tensor of shape (batch_size, n_obs, data_dim) or (batch_size, summary_dim) 
        Synthetic data sets generated by the params or summary statistics thereof
    kl_weight         : float in [0, 1]
        The weight of the KL regularization term

    Returns
    -------
    loss : tf.Tensor
        A single scalar Monte-Carlo approximation of the regularized Bayes risk, shape (,)
    """

    # Compute evidences
    alpha = network(sim_data)

    # Obtain probs
    model_probs = alpha / tf.reduce_sum(alpha, axis=1, keepdims=True)

    # Numerical stability
    model_probs = tf.clip_by_value(model_probs, 1e-15, 1 - 1e-15)

    # Actual loss + regularization (if given)
    loss = -tf.reduce_mean(tf.reduce_sum(model_indices * tf.math.log(model_probs), axis=1))
    if kl_weight > 0:
        kl = kl_dirichlet(model_indices, alpha)
        loss = loss + kl_weight * kl
    return loss


def kl_dirichlet(model_indices, alpha):
    """ Computes the KL divergence between a Dirichlet distribution with parameter vector alpha and a uniform Dirichlet.

    Parameters
    ----------
    model_indices : tf.Tensor of shape (batch_size, n_models)
        one-hot-encoded true model indices
    alpha         : tf.Tensor of shape (batch_size, n_models)
        positive network outputs in ``[1, +inf]``

    Returns
    -------
    kl: tf.Tensor
        A single scalar representing :math:`D_{KL}(\mathrm{Dir}(\\alpha) | \mathrm{Dir}(1,1,\ldots,1) )`, shape (,)
    """

    # Extract number of models
    J = int(model_indices.shape[1])

    # Set-up ground-truth preserving prior
    alpha = alpha * (1 - model_indices) + model_indices
    beta = tf.ones((1, J), dtype=tf.float32)
    alpha0 = tf.reduce_sum(alpha, axis=1, keepdims=True)

    # Computation of KL
    kl = tf.reduce_sum((alpha - beta) * (tf.math.digamma(alpha) - tf.math.digamma(alpha0)), axis=1, keepdims=True) + \
        tf.math.lgamma(alpha0) - tf.reduce_sum(tf.math.lgamma(alpha), axis=1, keepdims=True) + \
        tf.reduce_sum(tf.math.lgamma(beta), axis=1, keepdims=True) - tf.math.lgamma(
        tf.reduce_sum(beta, axis=1, keepdims=True))
    loss = tf.reduce_mean(kl)
    return loss


def maximum_mean_discrepancy(source_samples, target_samples, mmd_weight=1., minimum=0.):
    """ This Maximum Mean Discrepancy (MMD) loss is calculated with a number of different Gaussian kernels.

    Parameters
    ----------
    source_samples : tf.Tensor of shape (N, num_features)
    target_samples :  tf.Tensor of shape  (M, num_features)
    mmd_weight         : float, default: 1.0
        the weight of the MMD loss.
    minimum        : float, default: 0.0
        lower loss bound

    Returns
    -------
    loss_value : tf.Tensor
        A scalar Maximum Mean Discrepancy, shape (,)
    """

    loss_value = mmd_kernel(source_samples, target_samples, kernel=gaussian_kernel_matrix)
    loss_value = mmd_weight * tf.maximum(minimum, loss_value)
    return loss_value


def mmd_kl_gaussian_loss(network, *args, z_dist=tf.random.normal, mmd_weight=1.0):
    """KL loss in latent z space, MMD loss in summary space."""
    
    # Apply net and unpack 
    x_sum, out = network(*args, return_summary=True)
    z, log_det_J = out
    
    # Apply MMD loss to summary network output
    z_samples = z_dist(x_sum.shape) 
    mmd_loss = maximum_mean_discrepancy(x_sum, z_samples)
    
    # Apply KL loss for inference net
    kl_loss = tf.reduce_mean(0.5 * tf.square(tf.norm(z, axis=-1)) - log_det_J)
    
    # Sum and return losses
    return kl_loss + mmd_weight * mmd_loss


def mmd_kl_student_loss(network, *args, z_dist=tf.random.normal, mmd_weight=1.0):
    """KL loss in latent z space, MMD loss in summary space."""
    
    # Apply net and unpack 
    x_sum, out = network(*args, return_summary=True)
    v, z, log_det_J = out
    
    # Apply MMD loss to summary network output
    z_samples = z_dist(x_sum.shape) 
    mmd_loss = maximum_mean_discrepancy(x_sum, z_samples)
    
    # Apply KL loss for inference net
    d = z.shape[-1]
    kl_loss = 0.
    kl_loss -= d * tf.math.lgamma(0.5*(v + 1))
    kl_loss += d * tf.math.lgamma(0.5*v + 1e-15)
    kl_loss += (0.5*d) * tf.math.log(v + 1e-15)
    kl_loss += 0.5*(v+1) * tf.reduce_sum(tf.math.log1p(z**2 / v), axis=-1)
    kl_loss -= log_det_J
    kl_loss = tf.reduce_mean(kl_loss)
    
    # Sum and return losses
    return kl_loss + mmd_weight * mmd_loss