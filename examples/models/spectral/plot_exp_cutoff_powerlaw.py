r"""
.. _exp-cutoff-powerlaw-spectral-model:

Exponential Cutoff Powerlaw Spectral Model
==========================================

This model parametrises a cutoff power law spectrum.

It is defined by the following equation:

.. math::
    \phi(E) = \phi_0 \cdot \left(\frac{E}{E_0}\right)^{-\Gamma} \exp(- {(\lambda E})^{\alpha})

"""

# %%
# Example plot
# ------------
# Here is an example plot of the model:

from astropy import units as u
import matplotlib.pyplot as plt
from gammapy.modeling.models import ExpCutoffPowerLawSpectralModel, Models, SkyModel

energy_range = [0.1, 100] * u.TeV
model = ExpCutoffPowerLawSpectralModel(
    amplitude=2.076183759227292e-12 * u.Unit("cm-2 s-1 TeV-1"),
    index=1.8763343736076483,
    lambda_=0.08703226432146616 * u.Unit("TeV-1"),
    reference=1 * u.TeV,
)
model.plot(energy_range)
plt.grid(which="both")

# %%
# YAML representation
# -------------------
# Here is an example YAML file using the model:

model = SkyModel(spectral_model=model, name="exp-cutoff-power-law-model")
models = Models([model])

print(models.to_yaml())
