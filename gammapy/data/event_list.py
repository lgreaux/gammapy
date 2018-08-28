# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import absolute_import, division, print_function, unicode_literals
import logging
from collections import OrderedDict
import numpy as np
from astropy.units import Quantity
from astropy.coordinates import SkyCoord, Angle, AltAz
from astropy.table import Table
from astropy.table import vstack as vstack_tables
from ..utils.energy import EnergyBounds
from ..utils.fits import earth_location_from_dict
from ..utils.scripts import make_path
from ..utils.time import time_ref_from_dict
from ..utils.testing import Checker

__all__ = [
    'EventListBase',
    'EventList',
    'EventListLAT',
]

log = logging.getLogger(__name__)


class EventListBase(object):
    """Event list.

    This class represents the base for two different event lists:
    - EventList: targeted for IACT event lists
    - EventListLAT: targeted for Fermi-LAT event lists

    Event list data is stored in ``table`` (`~astropy.table.Table`) data member.

    The most important reconstructed event parameters
    are available as the following columns:

    - ``TIME`` - Mission elapsed time (sec)
    - ``RA``, ``DEC`` - ICRS system position (deg)
    - ``ENERGY`` - Energy (usually MeV for Fermi and TeV for IACTs)

    Other optional (columns) that are sometimes useful for high-level analysis:

    - ``GLON``, ``GLAT`` - Galactic coordinates (deg)
    - ``DETX``, ``DETY`` - Field of view coordinates (deg)

    Note that when reading data for analysis you shouldn't use those
    values directly, but access them via properties which create objects
    of the appropriate class:

    - `time` for ``TIME``
    - `radec` for ``RA``, ``DEC``
    - `energy` for ``ENERGY``
    - `galactic` for ``GLON``, ``GLAT``

    Parameters
    ----------
    table : `~astropy.table.Table`
        Event list table
    """

    def __init__(self, table):

        # TODO: remove this temp fix once we change to a new test dataset
        # This is a temp fix because this test dataset is used for many Gammapy tests
        # but it doesn't have the units set properly
        # '$GAMMAPY_EXTRA/datasets/hess-crab4-hd-hap-prod2'
        if 'ENERGY' in table.colnames:
            if not table['ENERGY'].unit:
                table['ENERGY'].unit = 'TeV'

        self.table = table

    @classmethod
    def read(cls, filename, **kwargs):
        """Read from FITS file.

        Format specification: :ref:`gadf:iact-events`

        Parameters
        ----------
        filename : `~gammapy.extern.pathlib.Path`, str
            Filename
        """
        filename = make_path(filename)
        kwargs.setdefault('hdu', 'EVENTS')
        table = Table.read(str(filename), **kwargs)
        return cls(table=table)

    @classmethod
    def stack(cls, event_lists, **kwargs):
        """Stack (concatenate) list of event lists.

        Calls `~astropy.table.vstack`.

        Parameters
        ----------
        event_lists : list
            list of `~gammapy.data.EventList` to stack
        """
        tables = [_.table for _ in event_lists]
        stacked_table = vstack_tables(tables, **kwargs)
        return cls(stacked_table)

    def __str__(self):
        ss = 'EventList info:\n'
        ss += '- Number of events: {}\n'.format(len(self.table))
        # TODO: add time, RA, DEC and if present GLON, GLAT info ...

        ss += '- Median energy: {}\n'.format(np.median(self.energy))

        if 'AZ' in self.table.colnames:
            # TODO: azimuth should be circular median
            ss += '- Median azimuth: {}\n'.format(np.median(self.table['AZ']))

        if 'ALT' in self.table.colnames:
            ss += '- Median altitude: {}\n'.format(np.median(self.table['ALT']))

        return ss

    @property
    def time_ref(self):
        """Time reference (`~astropy.time.Time`)"""
        return time_ref_from_dict(self.table.meta)

    @property
    def time(self):
        """Event times (`~astropy.time.Time`).

        Notes
        -----
        Times are automatically converted to 64-bit floats.
        With 32-bit floats times will be incorrect by a few seconds
        when e.g. adding them to the reference time.
        """
        met = Quantity(self.table['TIME'].astype('float64'), 'second')
        return self.time_ref + met

    @property
    def observation_time_start(self):
        """Observation start time (`~astropy.time.Time`)."""
        return self.time_ref + Quantity(self.table.meta['TSTART'], 'second')

    @property
    def observation_time_end(self):
        """Observation stop time (`~astropy.time.Time`)."""
        return self.time_ref + Quantity(self.table.meta['TSTOP'], 'second')

    @property
    def radec(self):
        """Event RA / DEC sky coordinates (`~astropy.coordinates.SkyCoord`).

        TODO: the `radec` and `galactic` properties should be cached as table columns
        """
        lon, lat = self.table['RA'], self.table['DEC']
        return SkyCoord(lon, lat, unit='deg', frame='icrs')

    @property
    def galactic(self):
        """Event Galactic sky coordinates (`~astropy.coordinates.SkyCoord`).

        Note: uses the ``GLON`` and ``GLAT`` columns.
        If only ``RA`` and ``DEC`` are present use the explicit
        ``event_list.radec.to('galactic')`` instead.
        """
        self.add_galactic_columns()
        lon, lat = self.table['GLON'], self.table['GLAT']
        return SkyCoord(lon, lat, unit='deg', frame='galactic')

    def add_galactic_columns(self):
        """Add Galactic coordinate columns to the table.

        Adds the following columns to the table if not already present:
        - "GLON" - Galactic longitude (deg)
        - "GLAT" - Galactic latitude (deg)
        """
        if set(['GLON', 'GLAT']).issubset(self.table.colnames):
            return

        galactic = self.radec.galactic
        self.table['GLON'] = galactic.l.degree
        self.table['GLAT'] = galactic.b.degree

    @property
    def observation_live_time_duration(self):
        """Live-time duration in seconds (`~astropy.units.Quantity`).

        The dead-time-corrected observation time.

        - In Fermi-LAT it is automatically provided in the header of the event list.
        - In IACTs is computed as ``t_live = t_observation * (1 - f_dead)``

        where ``f_dead`` is the dead-time fraction.
        """
        return Quantity(self.table.meta['LIVETIME'], 'second')

    @property
    def observation_dead_time_fraction(self):
        """Dead-time fraction (float).

        Defined as dead-time over observation time.

        Dead-time is defined as the time during the observation
        where the detector didn't record events:
        https://en.wikipedia.org/wiki/Dead_time
        https://adsabs.harvard.edu/abs/2004APh....22..285F

        The dead-time fraction is used in the live-time computation,
        which in turn is used in the exposure and flux computation.
        """
        return 1 - self.table.meta['DEADC']

    @property
    def altaz(self):
        """Event horizontal sky coordinates (`~astropy.coordinates.SkyCoord`)."""
        time = self.time
        location = self.observatory_earth_location
        altaz_frame = AltAz(obstime=time, location=location)

        lon, lat = self.table['AZ'], self.table['ALT']
        return SkyCoord(lon, lat, unit='deg', frame=altaz_frame)

    @property
    def pointing_radec(self):
        """Pointing RA / DEC sky coordinates (`~astropy.coordinates.SkyCoord`)."""
        info = self.table.meta
        lon, lat = info['RA_PNT'], info['DEC_PNT']
        return SkyCoord(lon, lat, unit='deg', frame='icrs')

    @property
    def offset(self):
        """Event offset from the array pointing position (`~astropy.coordinates.Angle`)."""
        position = self.radec
        center = self.pointing_radec
        offset = center.separation(position)
        return Angle(offset, unit='deg')

    @property
    def energy(self):
        """Event energies (`~astropy.units.Quantity`)."""
        return self.table['ENERGY'].quantity

    def select_row_subset(self, row_specifier):
        """Select table row subset.

        Parameters
        ----------
        row_specifier : slice, int, or array of ints
            Specification for rows to select,
            passed on to ``self.table[row_specifier]``.

        Returns
        -------
        event_list : `EventList`
            New event list with table row subset selected

        Examples
        --------
        Use a boolean mask as ``row_specifier``:

            mask = events.table['FOO'] > 42
            events2 = events.select_row_subset(mask)

        Use row index array as ``row_specifier``:

            idx = np.where(events.table['FOO'] > 42)[0]
            events2 = events.select_row_subset(idx)
        """
        table = self.table[row_specifier]
        return self.__class__(table=table)

    def select_energy(self, energy_band):
        """Select events in energy band.

        Parameters
        ----------
        energy_band : `~astropy.units.Quantity`
            Energy band ``[energy_min, energy_max)``

        Returns
        -------
        event_list : `EventList`
            Copy of event list with selection applied.

        Examples
        --------
        >>> from astropy.units import Quantity
        >>> from gammapy.data import EventList
        >>> event_list = EventList.read('events.fits')
        >>> energy_band = Quantity([1, 20], 'TeV')
        >>> event_list = event_list.select_energy()
        """
        energy = self.energy
        mask = (energy_band[0] <= energy)
        mask &= (energy < energy_band[1])
        return self.select_row_subset(mask)

    def select_time(self, time_interval):
        """Select events in time interval.
        """
        time = self.time
        mask = (time_interval[0] <= time)
        mask &= (time < time_interval[1])
        return self.select_row_subset(mask)

    def select_sky_cone(self, center, radius):
        """Select events in sky circle.

        Parameters
        ----------
        center : `~astropy.coordinates.SkyCoord`
            Sky circle center
        radius : `~astropy.coordinates.Angle`
            Sky circle radius

        Returns
        -------
        event_list : `EventList`
            Copy of event list with selection applied.
        """
        position = self.radec
        separation = center.separation(position)
        mask = separation < radius
        return self.select_row_subset(mask)

    def select_sky_ring(self, center, inner_radius, outer_radius):
        """Select events in ring region on the sky.

        Parameters
        ----------
        center : `~astropy.coordinates.SkyCoord`
            Sky ring center
        inner_radius, outer_radius : `~astropy.coordinates.Angle`
            Sky ring inner and outer radius

        Returns
        -------
        event_list : `EventList`
            Copy of event list with selection applied.
        """
        position = self.radec
        separation = center.separation(position)
        mask1 = inner_radius < separation
        mask2 = separation < outer_radius
        mask = mask1 * mask2
        return self.select_row_subset(mask)

    def select_sky_box(self, lon_lim, lat_lim, frame='icrs'):
        """Select events in sky box.

        TODO: move `gammapy.catalog.select_sky_box` to gammapy.utils.
        """
        from ..catalog import select_sky_box
        selected = select_sky_box(self.table, lon_lim, lat_lim, frame)
        return self.__class__(selected)

    def select_circular_region(self, region):
        """Select events in circular regions.

        TODO: Extend to support generic regions

        Parameters
        ----------
        region : `~regions.CircleSkyRegion` or list of `~regions.CircleSkyRegion`
            (List of) sky region(s)

        Returns
        -------
        event_list : `EventList`
            Copy of event list with selection applied.
        """
        if not isinstance(region, list):
            region = list([region])
        mask = self.filter_circular_region(region)
        return self.select_row_subset(mask)

    def filter_circular_region(self, region):
        """Create selection mask for event in given circular regions.

        TODO: Extend to support generic regions

        Parameters
        ----------
        region : list of `~regions.SkyRegion`
            List of sky regions

        Returns
        -------
        index_array : `numpy.ndarray`
            Index array of selected events
        """
        position = self.radec
        mask = np.array([], dtype=int)
        for reg in region:
            separation = reg.center.separation(position)
            temp = np.where(separation < reg.radius)[0]
            mask = np.union1d(mask, temp)
        return mask

    def plot_energy_hist(self, ax=None, ebounds=None, **kwargs):
        """Plot counts as a function of energy."""
        from ..spectrum import CountsSpectrum

        if ebounds is None:
            emin = np.min(self.table['ENERGY'].quantity)
            emax = np.max(self.table['ENERGY'].quantity)
            ebounds = EnergyBounds.equal_log_spacing(emin, emax, 100)

        spec = CountsSpectrum(energy_lo=ebounds[:-1], energy_hi=ebounds[1:])
        spec.fill(self.energy)  # leaving spec.fill(self) was triggering an issue for the LAT event list
        spec.plot(ax=ax, **kwargs)
        return ax

    def plot_time(self, ax=None):
        """Plots an event rate time curve.

        Parameters
        ----------
        ax : `~matplotlib.axes.Axes` or None
            Axes

        Returns
        -------
        ax : `~matplotlib.axes.Axes`
            Axes

        Examples
        --------
        Plot the rate of the events:

        .. plot::
            :include-source:

            import matplotlib.pyplot as plt
            from gammapy.data import DataStore

            ds = DataStore.from_dir('$GAMMAPY_EXTRA/datasets/hess-crab4-hd-hap-prod2')
            events = ds.obs(obs_id=23523).events
            events.plot_time()
            plt.show()
        """
        import matplotlib.pyplot as plt

        ax = plt.gca() if ax is None else ax

        time = self.table['TIME']
        first_event_time = np.min(time)

        # Note the events are not necessarily in time order
        relative_event_times = time - first_event_time

        ax.set_title('Event rate ')

        ax.set_xlabel('seconds')
        ax.set_ylabel('Events / s')
        rate, t = np.histogram(relative_event_times, bins=50)
        t_center = (t[1:] + t[:-1]) / 2

        ax.plot(t_center, rate)

        return ax

    def plot_offset2_distribution(self, ax=None, center=None, **kwargs):
        """Plot offset^2 distribution of the events.

        The distribution shown in this plot is for this quantity::

            offset = center.separation(events.radec).deg
            offset2 = offset ** 2

        Note that this method is just for a quicklook plot.

        If you want to do computations with the offset or offset^2 values, you can
        use the line above. As an example, here's how to compute the 68% event
        containment radius using `numpy.percentile`::

            import numpy as np
            r68 = np.percentile(offset, q=68)

        Parameters
        ----------
        ax : `~matplotlib.axes.Axes` (optional)
            Axes
        center : `astropy.coordinates.SkyCoord`
            Center position for the offset^2 distribution.
            Default is the observation pointing position.
        **kwargs :
            Extra keyword arguments are passed to `matplotlib.pyplot.hist`.

        Returns
        -------
        ax : `~matplotlib.axes.Axes`
            Axes

        Examples
        --------
        Load an example event list:

        >>> from gammapy.data import EventList
        >>> filename = '$GAMMAPY_EXTRA/test_datasets/unbundled/hess/run_0023037_hard_eventlist.fits.gz'
        >>> events = EventList.read(filename)

        Plot the offset^2 distribution wrt. the observation pointing position
        (this is a commonly used plot to check the background spatial distribution):

        >>> events.plot_offset2_distribution()

        Plot the offset^2 distribution wrt. the Crab pulsar position
        (this is commonly used to check both the gamma-ray signal and the background spatial distribution):

        >>> import numpy as np
        >>> from astropy.coordinates import SkyCoord
        >>> center = SkyCoord(83.63307, 22.01449, unit='deg')
        >>> bins = np.linspace(start=0, stop=0.3 ** 2, num=30)
        >>> events.plot_offset2_distribution(center=center, bins=bins)

        Note how we passed the ``bins`` option of `matplotlib.pyplot.hist` to control the histogram binning,
        in this case 30 bins ranging from 0 to (0.3 deg)^2.
        """
        import matplotlib.pyplot as plt
        ax = plt.gca() if ax is None else ax

        if center is None:
            center = self.pointing_radec

        offset2 = center.separation(self.radec).deg ** 2

        ax.hist(offset2, **kwargs)
        ax.set_xlabel('Offset^2 (deg^2)')
        ax.set_ylabel('Counts')

        return ax

    def check(self, checks='all'):
        """Run checks.

        This is a generator that yields a list of dicts.
        """
        checker = EventListChecker(self)
        return checker.run(checks=checks)


class EventList(EventListBase):
    """Event list for IACT dataset

    Data format specification: :ref:`gadf:iact-events`

    For further information, see the base class: `~gammapy.data.EventListBase`.

    Parameters
    ----------
    table : `~astropy.table.Table`
        Event list table

    Examples
    --------
    To load an example H.E.S.S. event list:

    >>> from gammapy.data import EventList
    >>> filename = '$GAMMAPY_EXTRA/test_datasets/unbundled/hess/run_0023037_hard_eventlist.fits.gz'
    >>> events = EventList.read(filename)
    """

    @property
    def observatory_earth_location(self):
        """Observatory location (`~astropy.coordinates.EarthLocation`)."""
        return earth_location_from_dict(self.table.meta)

    @property
    def observation_time_duration(self):
        """Observation time duration in seconds (`~astropy.units.Quantity`).
        This is a keyword related to IACTs
        The wall time, including dead-time.
        """
        return Quantity(self.table.meta['ONTIME'], 'second')

    @property
    def observation_dead_time_fraction(self):
        """Dead-time fraction (float).
        This is a keyword related to IACTs
        Defined as dead-time over observation time.

        Dead-time is defined as the time during the observation
        where the detector didn't record events:
        http://en.wikipedia.org/wiki/Dead_time
        http://adsabs.harvard.edu/abs/2004APh....22..285F

        The dead-time fraction is used in the live-time computation,
        which in turn is used in the exposure and flux computation.
        """
        return 1 - self.table.meta['DEADC']

    @property
    def altaz(self):
        """Event horizontal sky coordinates (`~astropy.coordinates.SkyCoord`)."""
        time = self.time
        location = self.observatory_earth_location
        altaz_frame = AltAz(obstime=time, location=location)

        lon, lat = self.table['AZ'], self.table['ALT']
        return SkyCoord(lon, lat, unit='deg', frame=altaz_frame)

    @property
    def pointing_radec(self):
        """Pointing RA / DEC sky coordinates (`~astropy.coordinates.SkyCoord`)."""
        info = self.table.meta
        lon, lat = info['RA_PNT'], info['DEC_PNT']
        return SkyCoord(lon, lat, unit='deg', frame='icrs')

    @property
    def offset(self):
        """Event offset from the array pointing position (`~astropy.coordinates.Angle`)."""
        position = self.radec
        center = self.pointing_radec
        offset = center.separation(position)
        return Angle(offset, unit='deg')

    def select_offset(self, offset_band):
        """Select events in offset band.

        Parameters
        ----------
        offset_band : `~astropy.coordinates.Angle`
            offset band ``[offset_min, offset_max)``

        Returns
        -------
        event_list : `EventList`
            Copy of event list with selection applied.
        """
        offset = self.offset
        mask = (offset_band[0] <= offset)
        mask &= (offset < offset_band[1])
        return self.select_row_subset(mask)

    def peek(self):
        """Summary plots."""
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(20, 8))
        self.plot_image_radec(ax=axes[0])
        self.plot_time(ax=axes[1])
        # TODO: self.plot_energy_dependence(ax=axes[x])
        # TODO: self.plot_offset_dependence(ax=axes[x])
        plt.tight_layout()

    def plot_image_radec(self, ax=None, number_bins=50):
        """Plot a sky counts image in RA/DEC coordinates.
        """
        import matplotlib.pyplot as plt
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        from matplotlib.colors import PowerNorm

        ax = plt.gca() if ax is None else ax

        count_image, x_edges, y_edges = np.histogram2d(
            self.table[:]['RA'], self.table[:]['DEC'], bins=number_bins)

        ax.set_title('# Photons')

        ax.set_xlabel('RA')
        ax.set_ylabel('DEC')

        ax.plot(self.pointing_radec.ra.value, self.pointing_radec.dec.value,
                '+', ms=20, mew=3, color='white')

        im = ax.imshow(count_image, interpolation='nearest', origin='low',
                       extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]],
                       norm=PowerNorm(gamma=0.5))

        ax.invert_xaxis()
        ax.grid()

        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.05)
        plt.colorbar(im, cax=cax)

    def plot_image(self, ax=None, number_bins=50):
        """Plot a counts image in field of view coordinates.
        """
        import matplotlib.pyplot as plt
        ax = plt.gca() if ax is None else ax

        max_x = max(self.table['DETX'])
        min_x = min(self.table['DETX'])
        max_y = max(self.table['DETY'])
        min_y = min(self.table['DETY'])

        x_edges = np.linspace(min_x, max_x, number_bins)
        y_edges = np.linspace(min_y, max_y, number_bins)

        count_image, x_edges, y_edges = np.histogram2d(
            self.table[:]['DETY'], self.table[:]['DETX'],
            bins=(x_edges, y_edges)
        )

        ax.set_title('# Photons')

        ax.set_xlabel('x / deg')
        ax.set_ylabel('y / deg')
        ax.imshow(count_image, interpolation='nearest', origin='low',
                  extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]])


class EventListLAT(EventListBase):
    """Event list for Fermi-LAT dataset

    Fermi-LAT data products
    https://fermi.gsfc.nasa.gov/ssc/data/analysis/documentation/Cicerone/Cicerone_Data/LAT_DP.html
    Data format specification (columns)
    https://fermi.gsfc.nasa.gov/ssc/data/analysis/documentation/Cicerone/Cicerone_Data/LAT_Data_Columns.html

    For further information, see the base class: `~gammapy.data.EventListBase`.

    Parameters
    ----------
    table : `~astropy.table.Table`
        Event list table

    Examples
    --------
    To load an example Fermi-LAT event list (the one corresponding to the 2FHL catalog dataset):

    >>> from gammapy.data import EventListLAT
    >>> filename = '$GAMMAPY_EXTRA/datasets/fermi_2fhl/2fhl_events.fits.gz'
    >>> events = EventListLAT.read(filename)
    """

    def plot_image(self):
        """Quick look counts map sky plot."""
        from ..maps import WcsNDMap
        m = WcsNDMap.create(
            npix=(360, 180), binsz=1.0, proj='AIT', coordsys='GAL',
        )
        coord = self.radec
        m.fill_by_coord(coord)
        m.plot(stretch='sqrt')


class EventListChecker(Checker):
    """Event list checker.

    Data format specification: ref:`gadf:iact-events`

    Parameters
    ----------
    event_list : `~gammapy.data.EventList`
        Event list
    """
    CHECKS = OrderedDict([
        ('meta', 'check_meta'),
        ('columns', 'check_columns'),
        ('times', 'check_times'),
        ('coordinates', 'check_coordinates'),
    ])

    accuracy = {
        'angle': Angle('1 arcsec'),
        'time': Quantity(1, 'microsecond'),
    }

    meta_required = [
        'OBS_ID', 'TELESCOP'
    ]

    columns_required = [
        'EVENT_ID',
        'RA',
        'DEC',
        'ENERGY',
    ]

    def __init__(self, event_list):
        self.event_list = event_list

    def obs_id(self):
        return self.event_list.table.meta['OBS_ID']

    def _record(self, level='info', msg=None):
        return {
            'level': level,
            'obs_id': self.obs_id,
            'msg': msg,
        }

    def check_meta(self):
        meta_missing = set(self.meta_required) - set(self.event_list.table.meta)
        if meta_missing:
            yield self._record(level='error', msg='Missing meta keys: {!r}'.format(meta_missing))

    def check_columns(self):
        columns_missing = set(self.columns_required) - set(self.event_list.table.colnames)
        if columns_missing:
            yield self._record(level='error', msg='Missing table columns: {!r}'.format(columns_missing))

    def check_coordinates(self):
        """Check if various event list coordinates are consistent."""
        self._check_coordinates_galactic()
        self._check_coordinates_altaz()

        # TODO: add FOV coordinates checks
        # self._check_coordinates_field_of_view()

    def _check_coordinates_galactic(self):
        """Check if RA / DEC matches GLON / GLAT."""
        event_list = self.dset.event_list

        for colname in ['RA', 'DEC', 'GLON', 'GLAT']:
            if colname not in event_list.table.colnames:
                # GLON / GLAT columns are optional ...
                # so it's OK if they are not present ... just move on ...
                self.logger.info('Skipping Galactic coordinate check. '
                                 'Missing column: "{}".'.format(colname))
                return True

        radec = event_list.radec
        galactic = event_list.galactic
        separation = radec.separation(galactic).to('arcsec')
        return self._check_separation(separation, 'GLON / GLAT', 'RA / DEC')

    def _check_coordinates_altaz(self):
        """Check if ALT / AZ matches RA / DEC."""
        event_list = self.dset.event_list

        for colname in ['RA', 'DEC', 'AZ', 'ALT']:
            if colname not in event_list.table.colnames:
                # AZ / ALT columns are optional ...
                # so it's OK if they are not present ... just move on ...
                self.logger.info('Skipping AltAz coordinate check. '
                                 'Missing column: "{}".'.format(colname))
                return True

        radec = event_list.radec
        altaz_expected = event_list.altaz
        altaz_actual = radec.transform_to(altaz_expected)
        separation = altaz_actual.separation(altaz_expected).to('arcsec')
        return self._check_separation(separation, 'ALT / AZ', 'RA / DEC')

    def _check_separation(self, separation, tag1, tag2):
        max_separation = separation.max()

        if max_separation > self.accuracy['angle']:
            # TODO: probably we need to print run number and / or other
            # things for this to be useful in a pipeline ...
            fmt = '{} not consistent with {}. Max separation: {}'
            args = [tag1, tag2, max_separation]
            self.logger.warning(fmt.format(*args))
            return False
        else:
            return True
