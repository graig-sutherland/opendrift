# This file is part of OpenDrift.
#
# OpenDrift is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 2
#
# OpenDrift is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with OpenDrift.  If not, see <https://www.gnu.org/licenses/>.
#
# Copyright 2015, Knut-Frode Dagestad, MET Norway

from datetime import datetime
import pyproj
import numpy as np
from netCDF4 import num2date
import logging
logger = logging.getLogger(__name__)

import pandas as pd
import xarray as xr
from opendrift.readers.basereader import BaseReader, StructuredReader
from opendrift.readers import open_dataset_opendrift, datetime_from_variable


class Reader(StructuredReader, BaseReader):
    """
    A reader for `CF-compliant <https://cfconventions.org/>`_ netCDF files. It can take a single file, a file pattern, a URL or an xarray Dataset.

    Args:
        :param filename: A single netCDF file, a pattern of files, or a xr.Dataset. The
                         netCDF file can also be an URL to an OPeNDAP server.
        :type filename: string, xr.Dataset (required).

        :param name: Name of reader
        :type name: string, optional

        :param proj4: PROJ.4 string describing projection of data.
        :type proj4: string, optional

    Example:

    .. code::

       from opendrift.readers.reader_netCDF_CF_generic import Reader
       r = Reader("arome_subset_16Nov2015.nc")

    Several files can be specified by using a pattern:

    .. code::

       from opendrift.readers.reader_netCDF_CF_generic import Reader
       r = Reader("*.nc")

    An OPeNDAP URL can be used:

    .. code::

       from opendrift.readers.reader_netCDF_CF_generic import Reader
       r = Reader('https://thredds.met.no/thredds/dodsC/mepslatest/meps_lagged_6_h_latest_2_5km_latest.nc')

    A xr.Dataset or a zarr dataset in an object store with auth can be used:

    .. code::

        from opendrift.readers.reader_netCDF_CF_generic import Reader
        r = Reader(ds, zarr_storage_options)
    """

    def __init__(self, filename=None, zarr_storage_options=None, name=None, proj4=None,
                 standard_name_mapping={}, ensemble_member=None):

        #if isinstance(filename, xr.Dataset):
        #    self.Dataset = filename
        #    if name is not None:
        #        self.name = name
        #    elif hasattr(self.Dataset, 'name'):
        #        self.name = self.Dataset.name
        #    else:
        #        self.name = str(filename)
        #else:
        #    if zarr_storage_options is not None:
        #        self.Dataset = xr.open_zarr(filename, storage_options=zarr_storage_options)
        #        if name is None:
        #            self.name = filename
        #        else:
        #            self.name = name
        #    else:
        #        if filename is None:
        #            raise ValueError('Need filename as argument to constructor')

        #        filestr = str(filename)
        #        if name is None:
        #            self.name = filestr
        #        else:
        #            self.name = name

        #        try:
        #            # Open file, check that everything is ok
        #            logger.info('Opening dataset: ' + filestr)
        #            if ('*' in filestr) or ('?' in filestr) or ('[' in filestr):
        #                logger.info('Opening files with MFDataset')
        #                self.Dataset = xr.open_mfdataset(filename, data_vars='minimal', coords='minimal',
        #                                                chunks={'time': 1}, decode_times=False)
        #            elif ensemble_member is not None:
        #                self.Dataset = xr.open_dataset(filename, decode_times=False).isel(ensemble_member=ensemble_member)
        #            else:
        #                self.Dataset = xr.open_dataset(filename, decode_times=False)
        #        except Exception as e:
        #            raise ValueError(e)

        self.Dataset = open_dataset_opendrift(source=filename, zarr_storage_options=zarr_storage_options)

        if name is None:
            self.name = str(filename)
        else:
            self.name = name

        # NB: check below might not be waterproof
        if 'ocean_time' in self.Dataset.dims and 'eta_u' in self.Dataset.dims and \
                'eta_rho' in self.Dataset.dims:
            raise ValueError('This seems to be a ROMS native file, should use ROMS native reader instead')

        logger.debug('Finding coordinate variables.')
        if proj4 is not None:  # If user has provided a projection apriori
            self.proj4 = proj4
        # Find x, y and z coordinates
        lon_var_name = None
        lat_var_name = None
        self.unitfactor = 1
        self.realizations = None
        self.ensemble_dimension = None
        self.dimensions = {}
        for var_name in self.Dataset.variables:
            var = self.Dataset.variables[var_name]

            if self.proj4 is None:
                if 'grid_mapping_name' in var.attrs:
                    logger.debug(
                        ('Parsing CF grid mapping dictionary:'
                        ' ' + str(var.attrs)))
                    try:  # parse proj4 with pyproj.CRS
                        crs = pyproj.CRS.from_cf(var.attrs)
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            self.proj4 = crs.to_proj4()
                    except:
                        logger.info('Could not parse CF grid_mapping')
                if self.proj4 is None:
                    if 'proj4' in var.attrs:
                        self.proj4 = str(var.attrs['proj4'])
                    elif 'proj4_string' in var.attrs:
                        self.proj4 = str(var.attrs['proj4_string'])

            standard_name = var.attrs['standard_name'] if 'standard_name' in var.attrs else ''
            long_name = var.attrs['long_name'] if 'long_name' in var.attrs else ''
            axis = var.attrs['axis'] if 'axis' in var.attrs else ''
            units = var.attrs['units'] if 'units' in var.attrs else ''
            CoordinateAxisType = var.attrs['CoordinateAxisType'] if 'CoordinateAxisType' in var.attrs else ''
            if standard_name == 'longitude' or \
                    CoordinateAxisType.lower() == 'lon' or \
                    long_name.lower() == 'longitude' or \
                    var_name.lower() in ['longitude', 'lon']:
                lon_var_name = var_name
            if standard_name == 'latitude' or \
                    CoordinateAxisType.lower() == 'lat' or \
                    long_name.lower() == 'latitude' or \
                    var_name.lower() in ['latitude', 'lat']:
                lat_var_name = var_name
            if (axis == 'X' or standard_name == 'projection_x_coordinate' or standard_name == 'grid_longitude') \
                    and var.ndim == 1:
                if len(var.dims)==1:
                    self.dimensions['x'] = var.dims[0]
                # Fix for units; should ideally use udunits package
                if units == 'km':
                    self.unitfactor = 1000
                elif units == '100  km':
                    self.unitfactor = 100000
                var_data = var.values
                x = var_data*self.unitfactor
            if (axis == 'Y' or standard_name == 'projection_y_coordinate' or standard_name == 'grid_latitude') \
                    and var.ndim == 1:
                if len(var.dims)==1:
                    self.dimensions['y'] = var.dims[0]
                # Fix for units; should ideally use udunits package
                if units == 'km':
                    self.unitfactor = 1000
                elif units == '100  km':
                    self.unitfactor = 100000
                var_data = var.values
                y = var_data*self.unitfactor
            if (standard_name == 'depth' or axis == 'Z') and var.ndim==1:
                var_data = var.values
                if len(var.dims)==1:
                    self.dimensions['z'] = var.dims[0]
                if var_data.ndim == 1:  # Earlier this was not a requirement above
                    if 'positive' not in var.attrs or \
                            var.attrs['positive'] == 'up':
                        self.z = var_data
                    else:
                        self.z = -var_data
            if standard_name == 'time' or axis == 'T' or var_name in ['time', 'vtime']:
                # Read and store time coverage (of this particular file)
                if len(var.dims)==1:
                    self.dimensions['time'] = var.dims[0]

                self.times = datetime_from_variable(var)
                if len(self.times) > 1:
                    if len(self.times) > 5:  # Check that times are not corrupted, necessary hack for NOAA winds on thredds
                        first_timestep = self.times[1] - self.times[0]
                        second_timestep = self.times[2] - self.times[1]
                        if first_timestep/second_timestep > 2:
                            logger.warning('First time steps is larger than second timestep, starting at second timestep')
                            self.times = self.times[1:]
                            self.Dataset = self.Dataset.isel({var.dims[0]: slice(1, len(var))})
                        second_last_timestep = self.times[-2] - self.times[-3]
                        last_timestep = self.times[-1] - self.times[-2]
                        if last_timestep/second_last_timestep > 2:
                            logger.warning('Last time steps is larger than second last timestep, stopping at second last timestep')
                            self.times = self.times[0:-2]
                            self.Dataset = self.Dataset.isel({var.dims[0]: slice(0, len(var)-1)})
                    self.time_step = self.times[1] - self.times[0]
                else:
                    self.time_step = None
                self.start_time = self.times[0]
                self.end_time = self.times[-1]

            if standard_name == 'realization':
                if ensemble_member == None:
                    var_data = np.atleast_1d(var.values)
                    self.realizations = var_data
                    logger.debug('%i ensemble members available'
                                % len(self.realizations))
                if len(var.dims)==1:
                    self.ensemble_dimension = var.dims[0]

        # Temporary workaround for Barents EPS model
        if self.realizations is None and 'ensemble_member' in self.Dataset.dims:
            self.realizations = np.arange(self.Dataset.dims['ensemble_member'])

        #########################
        # Summary of geolocation
        #########################
        if 'x' in locals():
            if x[1]-x[0] == 1 and y[1]-y[0] == 1:
                logger.info('deltaX and deltaY are 1, interpreting dataset as unprojected')
                projected = False
            else:
                projected = True
        if 'x' not in locals() or projected is False:  # No x/y-coordinates were detected
            if lon_var_name is None:
                raise ValueError('No geospatial coordinates were detected, cannot geolocate dataset')
            # We load lon and lat arrays into memory
            lon_var = self.Dataset.variables[lon_var_name]
            lat_var = self.Dataset.variables[lat_var_name]
            if lon_var.ndim == 1:
                logger.debug('Lon and lat are 1D arrays - using as projection coordinates')
                x = lon_var.data
                y = lat_var.data
                self.dimensions['x'] = lon_var.dims[0]
                self.dimensions['y'] = lat_var.dims[0]
                if self.proj4 is None:
                    self.proj4 = '+proj=latlong'
            elif lon_var.ndim == 2:
                logger.debug('Lon and lat are 2D arrays - dataset is unprojected')
                self.lon = lon_var.data
                self.lat = lat_var.data
                # Check if 2D arrays are repeated 1D arrays
                if np.array_equal(self.lon[0,:], self.lon[-1,:]) and np.array_equal(self.lat[:,0], self.lat[:,-1]):
                    logger.info('Lon and lat are repeated 1D arrays - i.e. lonlat projection')
                    x = self.lon[0,:]
                    y = self.lat[:,0]
                    self.dimensions['x'] = lon_var.dims[1]
                    self.dimensions['y'] = lat_var.dims[0]
                    if self.proj4 is None:
                        self.proj4 = '+proj=latlong'
                else:
                    self.dimensions['x'] = lon_var.dims[0]
                    self.dimensions['y'] = lat_var.dims[1]
                    self.projected = False
                    self.proj = None
                    self.proj4 = None
            elif lon_var.ndim == 3:
                logger.debug('Lon lat are 3D arrays, reading first time')
                self.lon = lon_var[0,:,:].data
                self.lat = lat_var[0,:,:].data
                self.dimensions['x'] = lon_var.dims[1]
                self.dimensions['y'] = lat_var.dims[2]
                self.projected = False
                self.proj = None
                self.proj4 = None
        else:
            if self.proj4 is None:
                logger.info('Grid coordinates are detected, but proj4 string not given: assuming latlong')
                self.proj4 = '+proj=latlong'

        if 'x' in locals() and 'y' in locals():
            self.numx = len(x)
            self.numy = len(y)
            self.xmin, self.xmax = x.min(), x.max()
            self.ymin, self.ymax = y.min(), y.max()
            self.delta_x = np.abs(x[1] - x[0])
            self.delta_y = np.abs(y[1] - y[0])
            rel_delta_x = (x[1::] - x[0:-1])
            rel_delta_x = np.abs((rel_delta_x.max() -
                                  rel_delta_x.min())/self.delta_x)
            rel_delta_y = (y[1::] - y[0:-1])
            rel_delta_y = np.abs((rel_delta_y.max() -
                                  rel_delta_y.min())/self.delta_y)
            if rel_delta_x > 0.05:  # Allow 5 % deviation
                print(rel_delta_x)
                print(x[1::] - x[0:-1])
                raise ValueError('delta_x is not constant!')
            if rel_delta_y > 0.05:
                print(rel_delta_y)
                print(y[1::] - y[0:-1])
                raise ValueError('delta_y is not constant!')
            self.x = x  # Store coordinate vectors
            self.y = y

        if self.proj4 is not None and 'latlong' in self.proj4 and self.xmax is not None and self.xmax > 360:
            logger.info('Longitudes > 360 degrees, subtracting 360')
            self.xmin -= 360
            self.xmax -= 360
            self.x -= 360

        logger.info(f'Detected dimensions: {self.dimensions}')

        ##########################################
        # Find all variables having standard_name
        ##########################################
        self.variable_mapping = {}
        skipvars = []
        for var_name in self.Dataset.variables:
            var = self.Dataset.variables[var_name]
            if var.ndim < 2:
                continue
            if var_name in standard_name_mapping:
                # User may specify mapping if standard_name is missing, or to override existing
                standard_name = standard_name_mapping[var_name]
                self.variable_mapping[standard_name] = str(var_name)
            elif 'standard_name' in var.attrs and 'hybrid' not in var.dims:
                # Skipping hybrid dim is workaround to prevent parsing upper winds from ECMWF
                # A permanent solution for selecting correct variable is needed
                standard_name = str(var.attrs['standard_name'])
                if standard_name in self.variable_aliases:  # Mapping if needed
                    standard_name = self.variable_aliases[standard_name]
                self.variable_mapping[standard_name] = str(var_name)
            else:
                skipvars.append(var_name)
        # Necessary hack for ECMWF with winds at several levels
        # TODO: must provide variable mapping along with URLs to create readers
        if self.variable_mapping.get('x_wind') is not None:
            if 'x_wind_200m' in self.Dataset.variables and 'x_wind_10m' in self.Dataset.variables:
                logger.warning('Shifting variable names of ECMWF data, to get winds at 10m')
                self.variable_mapping['x_wind'] = 'x_wind_10m'
                self.variable_mapping['y_wind'] = 'y_wind_10m'
                if self.dimensions.get('y') == 'latitude1' and 'latitude' in self.Dataset.variables:
                    self.dimensions['x'] = 'longitude'
                    self.dimensions['y'] = 'latitude'

        if len(skipvars) > 0:
            logger.debug('Skipped variables without standard_name: %s' % skipvars)

        self.variables = list(self.variable_mapping.keys())

        for vn, va in self.variable_mapping.items():
            if vn == 'sea_floor_depth_below_sea_level':
                var = self.Dataset.variables[va]
                if 'ensemble_member' in var.dims:
                    # Workaround for datasets with unnecessary ensemble dimension for static variables
                    logger.info(f'Removing ensemble dimension from {vn}')
                    var = var.isel(ensemble_member=0).squeeze()
                    self.Dataset[va] = var

        # Run constructor of parent Reader class
        super().__init__()

    def get_variables(self, requested_variables, time=None,
                      x=None, y=None, z=None,
                      indrealization=None):

        requested_variables, time, x, y, z, _outside = self.check_arguments(
            requested_variables, time, x, y, z)

        nearestTime, dummy1, dummy2, indxTime, dummy3, dummy4 = \
            self.nearest_time(time)

        if hasattr(self, 'z') and (z is not None):
            # Find z-index range
            # NB: may need to flip if self.z is ascending
            indices = np.searchsorted(-self.z, [-z.min(), -z.max()])
            indz = np.arange(np.maximum(0, indices.min() - 1 -
                                        self.verticalbuffer),
                             np.minimum(len(self.z), indices.max() + 1 +
                                        self.verticalbuffer))
            if len(indz) == 1:
                indz = indz[0]  # Extract integer to read only one layer
        else:
            indz = 0

        if indrealization == None:
            if self.realizations is not None:
                indrealization = range(len(self.realizations))
            else:
                indrealization = None

        # Find indices corresponding to requested x and y
        if hasattr(self, 'clipped'):
            clipped = self.clipped
        else: clipped = 0

        buffer = self.buffer  # Adding buffer, to cover also future positions of elements
        indy = np.floor(np.abs(y-self.y[0])/self.delta_y-clipped).astype(int) + clipped
        indy = np.arange(np.max([0, indy.min()-buffer]),
                         np.min([indy.max()+buffer, self.numy]))

        if self.global_coverage():  # Treatment of cyclic longitudes (x-coordinate)
            if self.lon_range() == '0to360':
                x = np.mod(x, 360)  # Shift x/lons to 0-360
            elif self.lon_range() == '-180to180':
                x = np.mod(x + 180, 360) - 180 # Shift x/lons to -180-180
        indx = np.floor(np.abs(x-self.x[0])/self.delta_x-clipped).astype(int) + clipped

        split = False
        if self.global_coverage():  # Check if need to split in two blocks
            uniqx = np.unique(indx)
            diff_xind = np.diff(uniqx)
            # We split if >800 pixels between left/west and right/east blocks
            if len(diff_xind)>=1 and diff_xind.max() > np.minimum(800, 0.6*self.numx):
                logger.debug('Requested data block crosses lon-border, reading and concatinating two parts')
                split = True
                splitind = np.argmax(diff_xind)
                indx_left = np.arange(0, uniqx[splitind] + buffer)
                indx_right = np.arange(uniqx[splitind+1] - buffer, self.numx)
                indx = np.concatenate((indx_right, indx_left))
        if split is False:
            indx = np.arange(np.maximum(0, indx.min()-buffer),
                             np.minimum(indx.max()+buffer+1, self.numx))

        variables = {}

        for par in requested_variables:
            if hasattr(self, 'rotate_mapping') and par in self.rotate_mapping:
                logger.debug('Using %s to retrieve %s' %
                    (self.rotate_mapping[par], par))
                if par not in self.variable_mapping:
                    self.variable_mapping[par] = \
                        self.variable_mapping[
                            self.rotate_mapping[par]]
            var = self.Dataset.variables[self.variable_mapping[par]]

            ensemble_dim = None
            dimindices = {'x': indx, 'y': indy, 'time': indxTime, 'z': indz}
            dimorder = list(var.dims)
            xnum = dimorder.index(self.dimensions['x'])
            ynum = dimorder.index(self.dimensions['y'])
            if xnum < ynum:
                # We must have y before x, since returning numpy arrays and not Xarrays
                logger.debug(f'Swapping order of x-y dimensions for {par}')
                dimorder[xnum] = self.dimensions['y']
                dimorder[ynum] = self.dimensions['x']
                var = var.permute_dims(*dimorder)

            # Remove any unknown dimensions
            for dim in var.dims:
                if dim not in self.dimensions.values() and dim != self.ensemble_dimension:
                    logger.debug(f'Removing unknown dimension: {dim}')
                    var = var.squeeze(dim=dim)
            if self.ensemble_dimension is not None and self.ensemble_dimension in var.dims:
                ensemble_dim = 0  # hardcoded, may not work for MEPS
            if split is False:
                if True:  # new dynamic way
                    subset = {vdim:dimindices[dim] for dim,vdim in self.dimensions.items() if vdim in var.dims}
                    variables[par] = var.isel(subset)
                #else:  # old hardcoded way, to be removed
                #    if var.ndim == 2:
                #        variables[par] = var[indy, indx]
                #    elif var.ndim == 3:
                #        variables[par] = var[indxTime, indy, indx]
                #    elif var.ndim == 4:
                #        variables[par] = var[indxTime, indz, indy, indx]
                #    elif var.ndim == 5:  # Ensemble data
                #        variables[par] = var[indxTime, indz, indrealization, indy, indx]
                #        ensemble_dim = 0  # Hardcoded ensemble dimension for now
                #    else:
                #        raise Exception('Wrong dimension of variable: ' +
                #                        self.variable_mapping[par])
            # The below should also be updated to dynamic subsetting
            else:  # We need to read left and right parts separately
                d_left = dimindices.copy()
                d_right = dimindices.copy()
                d_left.update({'x': indx_left})
                d_right.update({'x': indx_right})
                subset_left = {vdim:d_left[dim] for dim,vdim in self.dimensions.items()
                               if vdim in var.dims}
                subset_right = {vdim:d_right[dim] for dim,vdim in self.dimensions.items()
                               if vdim in var.dims}
                left = var.isel(subset_left)
                right = var.isel(subset_right)

                #if var.ndim == 2:
                #    left = var[indy, indx_left]
                #    right = var[indy, indx_right]
                #    variables[par] = xr.Variable.concat([left, right], dim=self.dimensions['x'])
                #elif var.ndim == 3:
                #    left = var[indxTime, indy, indx_left]
                #    right = var[indxTime, indy, indx_right]
                #    variables[par] = xr.Variable.concat([left, right], dim=self.dimensions['x'])
                #elif var.ndim == 4:
                #    left = var[indxTime, indz, indy, indx_left]
                #    right = var[indxTime, indz, indy, indx_right]
                #    variables[par] = xr.Variable.concat([left, right], dim=self.dimensions['x'])
                #elif var.ndim == 5:  # Ensemble data
                #    left = var[indxTime, indz, indrealization,
                #               indy, indx_left]
                #    right = var[indxTime, indz, indrealization,
                #                indy, indx_right]
                #    variables[par] = xr.Variable.concat([left, right], dim=self.dimensions['x'])

                #variables[par] = xr.Variable.concat([left, right], dim=self.dimensions['x'])
                variables[par] = xr.Variable.concat([right, left], dim=self.dimensions['x'])
                variables[par] = np.ma.masked_invalid(variables[par])

            # Mask values outside domain
            variables[par] = np.ma.array(variables[par],
                                         ndmin=2, mask=False)
            # Mask extreme values which might have slipped through
            with np.errstate(invalid='ignore'):
                variables[par] = np.ma.masked_outside(
                    variables[par], -30000, 30000)

            # Ensemble blocks are split into lists
            if ensemble_dim is not None:
                num_ensembles = variables[par].shape[ensemble_dim]
                logger.debug(f'Num ensembles for {par}: {num_ensembles}')
                newvar = [0]*num_ensembles
                for ensemble_num in range(num_ensembles):
                    newvar[ensemble_num] = \
                        np.take(variables[par],
                                ensemble_num, ensemble_dim)
                variables[par] = newvar

        # Store coordinates of returned points
        try:
            variables['z'] = self.z[indz]
        except:
            variables['z'] = None
        if self.projected is True:
            variables['x'] = self.x[indx]
            variables['y'] = self.y[indy]
            if split is True and not np.all(np.diff(variables['x'])>0):  # not monotonously increasing
                variables['x'] = np.mod(variables['x'], 360)  # Shift to 0-360
                if not np.all(np.diff(variables['x'])>0):  # not increasing, shift again to -180-180
                    variables['x'] = np.mod(variables['x'] + 180, 360) - 180
        else:
            variables['x'] = indx
            variables['y'] = indy
        variables['x'] = np.asarray(variables['x'], dtype=np.float32)
        variables['y'] = np.asarray(variables['y'], dtype=np.float32)

        variables['time'] = nearestTime

        # Rotate any east/north vectors if necessary
        if hasattr(self, 'rotate_mapping'):
            if self.y_is_north() is True:
                logger.debug('North is up, no rotation necessary')
            else:
                rx, ry = np.meshgrid(variables['x'], variables['y'])
                lon, lat = self.xy2lonlat(rx, ry)
                from opendrift.readers.basereader import vector_pairs_xy
                for vectorpair in vector_pairs_xy:
                    if vectorpair[0] in self.rotate_mapping and vectorpair[0] in variables.keys():
                        if self.proj.__class__.__name__ == 'fakeproj':
                            logger.warning('Rotation from fakeproj is not yet implemented, skipping.')
                            continue
                        logger.debug(f'Rotating vector from east/north to xy orientation: {vectorpair[0:2]}')
                        variables[vectorpair[0]], variables[vectorpair[1]] = self.rotate_vectors(
                            lon, lat, variables[vectorpair[0]], variables[vectorpair[1]],
                            pyproj.Proj('+proj=latlong'), self.proj)

        if hasattr(self, 'shift_x'):
            # "hidden feature": if reader.shift_x and reader.shift_y are defined,
            # the returned fields are shifted this many meters in the x- and y directions
            # E.g. reader.shift_x=10000 gives a shift 10 km eastwards (if x is east direction)
            if self.proj.crs.is_geographic:  # meters to degrees
                shift_y = (self.shift_y/111000)
                shift_x = (self.shift_x/111000)*np.cos(np.radians(variables['y']))
                logger.info('Shifting x between %s and %s' % (shift_x.min(), shift_x.max()))
                logger.info('Shifting y with %s m' % shift_y)
            else:
                shift_x = self.shift_x
                shift_y = self.shift_y
                logger.info('Shifting x with %s m' % shift_x)
                logger.info('Shifting y with %s m' % shift_y)
            variables['x'] += shift_x
            variables['y'] += shift_y

        return variables