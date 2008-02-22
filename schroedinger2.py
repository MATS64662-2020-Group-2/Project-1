#!/usr/bin/env python
"""
Usage:
------

Create a mesh:

$ ./convert.py 

Solve:

$ ./schroedinger.py

Visualize:

$ paraview --data=t.1.vtk

"""
# 12.01.2007, c 
import os.path as op
from optparse import OptionParser
from scipy.optimize import broyden3
from scipy.optimize.nonlin import excitingmixing


import init_sfe
from sfe.base.base import *
from sfe.base.conf import ProblemConf
from sfe.base.la import eig
from sfe.fem.evaluate import evalTermOP
import sfe.base.ioutils as io
from sfe.fem.problemDef import ProblemDefinition
from sfe.homogenization.phono import processOptions
from sfe.solvers.generic import getStandardKeywords
from solve import solve

##
# c: 22.02.2008, r: 22.02.2008
def updateStateToOutput( out, pb, vec, name, fillValue = None ):
    aux = pb.stateToOutput( vec, fillValue )
    key = aux.keys()[0]
    out[name] = aux[key]

##
# c: 22.02.2008, r: 22.02.2008
def wrapFunction( function, args ):
    ncalls = [0]
    times = []
    def function_wrapper( x ):
        ncalls[0] += 1
        tt = time.time()
        out = function( x, *args )
        eigs, mtxSPhi, vecN, vecVH, vecVXC = out
        print vecVH
        print vecVXC
        tt2 = time.time()
        if tt2 < tt:
            raise RuntimeError, '%f >= %f' % (tt, tt2)
        times.append( tt2 - tt )
        return vecVH + vecVXC
    return ncalls, times, function_wrapper

##
# c: 22.02.2008, r: 22.02.2008
def iterate( vecVHXC, pb, conf, nEigs, mtxB, nElectron = 5 ):
    import rdirac

    pb.updateMaterials( extraMatArgs = {'matV' : {'vhxc' : vecVHXC}} )

    dummy = pb.createStateVector()

    output( 'assembling lhs...' )
    tt = time.clock()
    mtxA = evalTermOP( dummy, conf.equations['lhs'], pb,
                       dwMode = 'matrix', tangentMatrix = pb.mtxA )
    output( '...done in %.2f s' % (time.clock() - tt) )


    print 'computing resonance frequencies...'
    if nEigs == mtxA.shape[0]:
        tt = [0]
        eigs, mtxSPhi = eig( mtxA.toarray(), mtxB.toarray(), returnTime = tt )
        print 'done in %.2f s' % tt[0]
    else:
        eigs, mtxSPhi = solve(mtxA, mtxB, conf.options.nEigs)
    print eigs

    vecPhi = nm.zeros_like( vecVHXC )
    vecN = nm.zeros_like( vecVHXC )
    for ii in xrange( nElectron ):
        vecPhi = pb.variables.makeFullVec( mtxSPhi[:,ii] )
        vecN += vecPhi ** 2

    vecVXC = nm.zeros_like( vecVHXC )
    for ii, val in enumerate( vecN ):
        vecVXC[ii] = rdirac.getvxc( val, 0 )

    pb.setEquations( conf.equations_vh )
    pb.timeUpdate()
    pb.variables['n'].dataFromData( vecN )
    vecVH = pb.solve()

    return eigs, mtxSPhi, vecN, vecVH, vecVXC

##
# c: 01.02.2008, r: 22.02.2008
def solveEigenProblem( conf, options ):

    if options.outputFileNameTrunk:
        ofnTrunk = options.outputFileNameTrunk
    else:
        ofnTrunk = io.getTrunk( conf.fileName_mesh )

    pb = ProblemDefinition.fromConf( conf )
    dim = pb.domain.mesh.dim

    pb.timeUpdate()

    dummy = pb.createStateVector()

    output( 'assembling rhs...' )
    tt = time.clock()
    mtxB = evalTermOP( dummy, conf.equations['rhs'], pb,
                       dwMode = 'matrix', tangentMatrix = pb.mtxA.copy() )
    output( '...done in %.2f s' % (time.clock() - tt) )

    #mtxA.save( 'tmp/a.txt', format='%d %d %.12f\n' )
    #mtxB.save( 'tmp/b.txt', format='%d %d %.12f\n' )

    try:
        nEigs = conf.options.nEigs
    except AttributeError:
        nEigs = mtxA.shape[0]

    if nEigs is None:
        nEigs = mtxA.shape[0]

##     mtxA.save( 'a.txt', format='%d %d %.12f\n' )
##     mtxB.save( 'b.txt', format='%d %d %.12f\n' )

    vecVHXC = nm.zeros( (pb.variables.di.ptr[-1],), dtype = nm.float64 )
    ncalls, times, nonlinV = wrapFunction( iterate,
                                           (pb, conf, nEigs, mtxB) )

    vecVHXC = broyden3( nonlinV, vecVHXC, verbose = True )
    out = iterate( vecVHXC, pb, conf, nEigs, mtxB )
    eigs, mtxSPhi, vecN, vecVH, vecVXC = out

    coor = pb.domain.getMeshCoors()
    r = coor[:,0]**2 + coor[:,1]**2 + coor[:,2]**2
    vecN *= r
    
    nEigs = eigs.shape[0]
    opts = processOptions( conf.options, nEigs )

    mtxPhi = nm.empty( (pb.variables.di.ptr[-1], mtxSPhi.shape[1]),
                       dtype = nm.float64 )
    for ii in xrange( nEigs ):
        mtxPhi[:,ii] = pb.variables.makeFullVec( mtxSPhi[:,ii] )

    out = {}
    for ii in xrange( nEigs ):
        if opts.save is not None:
            if (ii > opts.save[0]) and (ii < (nEigs - opts.save[1])): continue
        aux = pb.stateToOutput( mtxPhi[:,ii] )
        key = aux.keys()[0]
        out[key+'%03d' % ii] = aux[key]

    updateStateToOutput( out, pb, vecN, 'nr2' )
    updateStateToOutput( out, pb, vecVH, 'vh' )
    updateStateToOutput( out, pb, vecVXC, 'vxc' )

    pb.domain.mesh.write( ofnTrunk + '.vtk', io = 'auto', out = out )

    fd = open( ofnTrunk + '_eigs.txt', 'w' )
    eigs.tofile( fd, ' ' )
    fd.close()

    return Struct( pb = pb, eigs = eigs, mtxPhi = mtxPhi )


usage = """%prog [options] fileNameIn"""

help = {
    'fileName' :
    'basename of output file(s) [default: <basename of input file>]',
}

##
# c: 01.02.2008, r: 19.02.2008
def main():
    version = open( op.join( init_sfe.install_dir,
                             'VERSION' ) ).readlines()[0][:-1]

    parser = OptionParser( usage = usage, version = "%prog " + version )
    parser.add_option( "-o", "", metavar = 'fileName',
                       action = "store", dest = "outputFileNameTrunk",
                       default = None, help = help['fileName'] )

    options, args = parser.parse_args()

    if (len( args ) == 1):
        fileNameIn = args[0];
    else:
        fileNameIn = "input/schroed2.py"
    
    required, other = getStandardKeywords()
    required.remove( 'solver_[0-9]+|solvers' )
    conf = ProblemConf.fromFile( fileNameIn, required, other )
##     print conf
##     pause()

    evp = solveEigenProblem( conf, options )

if __name__ == '__main__':
    main()
