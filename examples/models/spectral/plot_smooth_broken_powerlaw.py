r"""
.. _smooth-broken-powerlaw-spectral-model:

Smooth Broken Power Law Spectral Model
======================================

This model parametrises a smooth broken power law spectrum.

It is defined by the following equation:

.. math::
    \phi(E) = \phi_0 \cdot \left( \frac{E}{E_0} \right)^{-\Gamma1}\left(1 + \frac{E}{E_{break}}^{\frac{\Gamma2-\Gamma1}{\beta}} \right)^{-\beta}
"""

# %%
# Example plot
# ------------
# Here is an example plot of the model:

from astropy import units as u
import matplotlib.pyplot as plt
from gammapy.modeling.models import Models, SkyModel, SmoothBrokenPowerLawSpectralModel

energy_range = [0.1, 100] * u.TeV
model = SmoothBrokenPowerLawSpectralModel(
    index1=1.5 * u.Unit(""),
    index2=2.5 * u.Unit(""),
    amplitude=4 / u.cm ** 2 / u.s / u.TeV,
    ebreak=0.5 * u.TeV,
    reference=1 * u.TeV,
    beta=1,
)
model.plot(energy_range)
plt.grid(which="both")

# %%
# YAML representation
# -------------------
# Here is an example YAML file using the model:

model = SkyModel(spectral_model=model, name="smooth-broken-power-law-model")
models = Models([model])

print(models.to_yaml())
