import numpy as np
import tensorflow as tf
from tensorflow.keras.utils import to_categorical


class MetaAmortizer(tf.keras.Model):

    def __init__(self, inference_net=None, evidence_net=None, summary_net=None):
        """ 
        Connects an evidential network with a summary network as in the BayesFlow for model comparison set-up.

        Parameters
        ----------
        inference_net : tf.keras.Model
            An (invertible) inference network which processes the outputs of a generative model (i.e., params, sim_data)
        evidence_net  : tf.keras.Model
            An evidential network which processes the outputs of multiple generative models (i.e., sim_data)
        summary_net   : tf.keras.Model or None, optional, default: None
            An optional summary network
        """
        super(MetaAmortizer, self).__init__()

        self.inference_net = inference_net
        self.evidence_net = evidence_net
        self.summary_net = summary_net

    def call(self, model_indices, params, sim_data):
        """ 
        Performs a forward pass through the networks.

        Parameters
        ---------
        model_indices  : tf.Tensor or np.array of shape (n_sim, n_models)
            the true, one-hot-encoded model indices :math:`m \sim p(m)`
        params         : tf.Tensor or np.array of shape (n_sim, n_params)
            the parameters :math:`\\theta \sim p(\\theta | m)` of interest
        sim_data       : tf.Tensor or np.array of shape (n_sim, n_obs, data_dim)
            the conditional data `x`

        Returns
        -------
        out_inference: np.array
            The output of the inference network or ``None`` if no networks provided
        out_evidence: np.array
            The output of the evidence network or ``None`` if no networks provided

        """

        # TODO - Model aware or model-agnostic summary
        if self.summary_net is not None:
            sim_data = self.summary_net(sim_data, model_indices)

        if self.evidence_net is not None:
            out_evidence = self.evidence_net(sim_data)
        else:
            out_evidence = None

        if self.inference_net is not None:
            out_inference = self.inference_net(model_indices, params, sim_data)
        else:
            out_inference = None
        return out_inference, out_evidence

    def sample_from_model(self, x_obs, model_idx, n_samples):
        """Performs fast parallelized inference on a single model specified by model_idx).

        Parameters
        ----------
        x_obs     : np.ndarray or tf.Tensor of shape (n_datasets, n_obs, data_dim) or (n_datasets, summary_dim) 
            The observed (set of) dataset(s)
        model_idx : int in (0,...n_models-1)
            The model index which sepcified from which model the sampled are obtained.
        n_samples : int > 1
            The number of samples to be obtained from the posterior of the model spcified by model_idx

        Returns
        ----------
        samples : np.ndarray of shape (n_samples, n_datasets, n_params_m) 
            The posterior samples from the approximate posterior of the specified model.
        """

        n_datasets = x_obs.shape[0]
        model_idx_oh = to_categorical([model_idx] * n_datasets, num_classes=self.inference_net.n_models)
        raise NotImplementedError('TODO!')

    def compare_models(self, x_obs):
        """Performs model comparison on an observed data set.

        Parameters
        ----------
        x_obs : np.ndarray or tf.Tensor of shape (n_datasets, n_obs, data_dim) or (n_datasets, summary_dim) 
            The observed (set of) dataset(s)

        Returns
        ----------
        est_probs : np.ndarray of shape (n_datasets, n_models) 
            The estimated posterior model probabilities (PMPs)
        """

        if self.summary_net is not None:
            x_obs = self.summary_net(x_obs)
        est_probs = self.evidence_net(x_obs).numpy()
        return est_probs


class MultiModelAmortizer(tf.keras.Model):
    """ Connects an evidential network with a summary network as in the BayesFlow for model comparison set-up.
    """

    def __init__(self, evidence_net, summary_net=None):
        """Initializes a MultiModelAmortizer for amortized model comparison.

        Parameters
        ----------
        evidence_net  : tf.keras.Model
            An evidential network which processes the outputs of multiple generative models (i.e., sim_data)
        summary_net   : tf.keras.Model or None, optional, default: None
            An optional summary network
        """
        super(MultiModelAmortizer, self).__init__()

        self.evidence_net = evidence_net
        self.summary_net = summary_net

    def call(self, sim_data):
        """Performs a forward pass through the summary and inference network.

        Parameters
        ----------
        sim_data  : tf.Tensor of shape (batch_size, n_obs, data_dim)
            The conditional data `x`

        Returns
        -------
        out : np.array
            The outputs of ``evidence_net(summary_net(x))``, usually model probabilities or absolute evidences
        """

        # Compute learnable summaries, if given
        if self.summary_net is not None:
            sim_data = self.summary_net(sim_data)

        # Compute output of inference net
        out = self.evidence_net(sim_data)
        return out

    def sample(self, obs_data, n_samples, **kwargs):
        """Performs inference on actually observed or simulated validation data.

        Parameters
        ----------
        obs_data  : tf.Tensor of shape (n_datasets, n_obs, data_dim)
            The conditional data set(s)
        n_samples : int
            The number of posterior samples to obtain from the approximate posterior

        Returns
        -------
        post_samples : tf.Tensor of shape (n_samples, n_datasets, n_models)
            The sampled model indices or evidences per dataset or model
        """

        # Compute learnable summaries, if given
        if self.summary_net is not None:
            obs_data = self.summary_net(obs_data)

        post_samples = self.evidence_net.sample(obs_data, n_samples, **kwargs)
        return post_samples


class SingleModelAmortizer(tf.keras.Model):
    """ Connects an inference network for parameter estimation with an optional summary network
    as in the original BayesFlow set-up.
    """
    def __init__(self, inference_net, summary_net=None):
        """Initializes the SingleModelAmortizer

        Parameters
        ----------
        inference_net : tf.keras.Model
            An (invertible) inference network which processes the outputs of a generative model (i.e., params, sim_data)
        summary_net   : tf.keras.Model or None, optional, default: None
            An optional summary network
        """
        super(SingleModelAmortizer, self).__init__()

        self.inference_net = inference_net
        self.summary_net = summary_net

    def call(self, params, sim_data, return_summary=False):
        """ Performs a forward pass through the summary and inference network.

        Parameters
        ----------
        params    : tf.Tensor of shape (batch_size, n_params)
            the parameters theta ~ p(theta | x) of interest
        sim_data  : tf.Tensor of shape (batch_size, n_obs, data_dim)
            the conditional data x
        return_summary : bool
            a flag which determines whether the data summaryis returned or not
        Returns
        -------
        out
            the outputs of ``inference_net(theta, summary_net(x))``, usually a latent variable and
            log(det(Jacobian)), that is a tuple ``(z, log_det_J) or sum_data, (z, log_det_J) if 
            return_summary is set to True and a summary network is defined.`` 
        """

        # Compute learnable summaries, if given
        if self.summary_net is not None:
            sim_data = self.summary_net(sim_data)

        # Compute output of inference net
        out = self.inference_net(params, sim_data)

        if not return_summary:
            return out
        return sim_data, out

    def sample(self, obs_data, n_samples, **kwargs):
        """ Performs inference on actually observed or simulated validation data.


        Parameters
        ----------

        obs_data  : tf.Tensor of shape (n_datasets, n_obs, data_dim)
            The conditional data set(s)
        n_samples : int
            The number of posterior samples to obtain from the approximate posterior

        Returns
        -------
        post_samples : tf.Tensor of shape (n_samples, n_datasets, n_params)
            the sampled parameters per data set
        """

        # Compute learnable summaries, if given
        if self.summary_net is not None:
            obs_data = self.summary_net(obs_data)

        post_samples = self.inference_net.sample(obs_data, n_samples, **kwargs)
        return post_samples


class PosteriorLikelihoodAmortizer(tf.keras.Model):
    """ Connects an inference network for parameter estimation with an optional summary network
    as in the original BayesFlow set-up.
    """

    def __init__(self, posterior_net, likelihood_net):
        """Initializes the PosteriorLikelihoodAmortizer

        Parameters
        ----------
        posterior_net  : SingleModelAmortizer(tf.keras.Model)
            An (invertible) inference network which processes the outputs of a generative model (i.e., params, sim_data)
        likelihood_net : SingleModelAmortizer(tf.keras.Model)
            An (invertible) inference network which processes the outputs of a generative model (i.e., sim_data, params)

        """
        super(PosteriorLikelihoodAmortizer, self).__init__()

        self.posterior_net = posterior_net
        self.likelihood_net = likelihood_net

    def call(self, params, sim_data, return_summary=False):
        """ Performs a forward pass through the summary and inference network.

        Parameters
        ----------
        params    : tf.Tensor of shape (batch_size, n_params)
            the parameters theta ~ p(theta | x) of interest
        sim_data  : tf.Tensor of shape (batch_size, n_obs, data_dim)
            the conditional data x
        return_summary : bool
            a flag which determines whether the data summaryis returned or not
        Returns
        -------
        out
            the outputs of ``inference_net(theta, summary_net(x))``, usually a latent variable and
            log(det(Jacobian)), that is a tuple ``(z, log_det_J) or sum_data, (z, log_det_J) if 
            return_summary is set to True and a summary network is defined.`` 
        """

        # Compute output of posteriior net
        out_post = self.posterior_net(params, sim_data, return_summary=return_summary)

        # Compute output of likelihood network
        out_lik = self.likelihood_net(sim_data, params)
        
        if not return_summary:
            return out_post, out_lik
        return sim_data, out_post, out_lik

    def sample_params_given_data(self, obs_data, n_samples, **kwargs):
        """ Performs posterior inference on actually observed or simulated validation data.


        Parameters
        ----------

        obs_data  : tf.Tensor of shape (n_datasets, n_obs, data_dim)
            The conditional data set(s)
        n_samples : int
            The number of posterior samples to obtain from the approximate posterior

        Returns
        -------
        post_samples : tf.Tensor of shape (n_samples, n_datasets, n_params)
            the sampled parameters per data set
        """

        post_samples = self.posterior_net.sample(obs_data, n_samples, **kwargs)
        return post_samples

    def sample_data_given_params(self, params, n_samples, **kwargs):
        """ Generates data from a synthetic likelihood given parameters.


        Parameters
        ----------

        params    : tf.Tensor of shape (n_datasets, params_dim)
            The conditional data set(s)
        n_samples : int
            The number of samples to obtain from the approximate likelihood.

        Returns
        -------
        lik_samples : tf.Tensor of shape (n_obs, n_datasets, data_dim)
            the sampled parameters per data set
        """

        lik_samples = self.likelihood_net.sample(params, n_samples, **kwargs)
        return lik_samples

    def log_likelihood(self, obs_data, params, normalized=True):
        """ Calculates the approximate log-likelihood of params given obs_data.

        Parameters
        ----------
        obs_data   : tf.Tensor of shape (batch_size, n_obs, data_dim)
            the data of interest x_n ~ p(x | theta) 
        params     : tf.Tensor of shape (batch_size, n_params)
            the parameters of interest theta ~ p(theta | x) 
        normalized : bool
            a flag which determines whether the likelihood is normalzied or not.

        Returns
        -------
        loglik     : tf.Tensor of shape (batch_size, n_obs)
            the approximate log-likelihood of each data point in each data set
        """

        z, log_det_J = self.likelihood_net(obs_data, params)
        k = z.shape[-1]
        log_z_unnorm = -0.5 * tf.math.square(tf.norm(z, axis=-1)) 
        if normalized:
            log_z = log_z_unnorm - tf.math.log(tf.math.sqrt((2*np.pi)**k))
        else:
            log_z = log_z_unnorm
        loglik = log_z + log_det_J
        return loglik

    def log_posterior(self, params, obs_data):
        """ Calculates the approximate log-posterior of params given obs_data.

        Parameters
        ----------
        params     : tf.Tensor of shape (batch_size, n_params)
            the parameters of interest theta ~ p(theta | x) 
        obs_data   : tf.Tensor of shape (batch_size, n_obs, data_dim)
            the data of interest x_n ~ p(x | theta) 

        Returns
        -------
        loglik     : tf.Tensor of shape (batch_size, n_obs)
            the approximate log-likelihood of each data point in each data set
        """
        z, log_det_J = self.posterior_net(params, obs_data)
        k = z.shape[-1]
        log_z_unnorm = -0.5 * tf.math.square(tf.norm(z, axis=-1)) 
        log_z = log_z_unnorm - tf.math.log(tf.math.sqrt((2*np.pi)**k))
        return log_z + log_det_J