import pickle as pkl
import numpy as np
from sklearn.metrics.pairwise import euclidean_distances
import copy, csv
from rdkit import Chem
from rdkit.Chem import AllChem
import pdb
import pickle as pkl
import os
import time
import argparse
import getpass
parser = argparse.ArgumentParser(description='Run baseline model')

parser.add_argument('--data', type=str, default='COD', choices=['COD','QM9'], help='which dataset to use')
parser.add_argument('--use-val', action='store_true', help='use validation set instead of test set')
parser.add_argument('--savedir', type=str, default='./', help='save directory of results')
parser.add_argument('--num-total-samples', type=int, default=10, help='number of total samples to use per molecule')
parser.add_argument('--num-parallel-samples', type=int, default=10, help='number of parallel samples to use per molecule')
parser.add_argument('--num-threads', type=int, default=4, help='number of threads to use')
parser.add_argument('--savepermol', action='store_true', help='save mmff and uff results per molecule')
parser.add_argument('--setting', type=str, default='default', choices=['default', 'ignorefailures'], help='setting of embed molecule')


args = parser.parse_args()

def data_path():
    """Path to data depending on user launching the script"""
    if getpass.getuser() == "mansimov":
        if os.uname().nodename == "mansimov-desktop":
            return "./data/"
        else:
            return "/misc/kcgscratch1/ChoGroup/mansimov/seokho_drive_datasets/"
    if getpass.getuser() == "em3382":
        return "/scratch/em3382/seokho_drive_datasets/"
    else:
        return "./"

if args.data == "COD":
    n_max=50
    nval=3000
    ntst=3000

elif args.data == "QM9":
    n_max=9
    nval=5000
    ntst=5000

[suppl, molsmi] = pkl.load(open(data_path()+str(args.data)+'_molset_'+str(n_max)+'.p','rb'))
assert (len(suppl) == len(molsmi))
ntrn = len(suppl) - nval - ntst
# use validation set
if args.use_val:
    suppl = suppl[ntrn:ntrn+nval]
    molsmi = molsmi[ntrn:ntrn+nval]
    nmols = nval
# use test set
else:
    suppl = suppl[ntrn+nval:ntrn+nval+ntst]
    molsmi = molsmi[ntrn+nval:ntrn+nval+ntst]
    nmols = ntst

print (':::{}'.format("val" if args.use_val else "test"))
# save uff and mmff results
uff = []
mmff = []
data_split = '_val_' if args.use_val else '_test_'
if args.savepermol:
    # create dir
    dir_name = os.path.join(args.savedir, args.data, data_split)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)
t1 = time.time()
for t in range(nmols):
    if t % 10 == 0 :
        t2 = time.time()
        print (t, nmols, molsmi[t])
        print ("time spent {}".format(t2-t1))
        t1 = time.time()
    mol_ref=copy.deepcopy(suppl[t])

    Chem.rdmolops.AssignAtomChiralTagsFromStructure(mol_ref)
    Chem.rdmolops.AssignStereochemistry(mol_ref)

    mol_smi = Chem.MolFromSmiles(molsmi[t])

    n_est = mol_ref.GetNumHeavyAtoms()
    n_rot_bonds = AllChem.CalcNumRotatableBonds(mol_ref)

    ttest_uff = []
    ttest_mmff = []
    assert (args.num_total_samples % args.num_parallel_samples == 0)
    iters = args.num_total_samples // args.num_parallel_samples
    for repid in range(iters):
        mol_init_1=Chem.AddHs(mol_ref)
        # remove all conformers from molecule
        mol_init_1.RemoveAllConformers()
        # get multiple conformers
        if args.setting == 'ignorefailures':
            useRandomCoords=True
            enforceChirality=False
            ignoreSmoothingFailures=True
        elif args.setting == 'default':
            useRandomCoords=False
            enforceChirality=True
            ignoreSmoothingFailures=False

        AllChem.EmbedMultipleConfs(mol_init_1,args.num_parallel_samples,\
                                    numThreads=args.num_threads,\
                                    useRandomCoords=useRandomCoords,\
                                    enforceChirality=enforceChirality,\
                                    ignoreSmoothingFailures=ignoreSmoothingFailures)

        try:
            ## baseline force field part with UFF
            mol_baseUFF = copy.deepcopy(mol_init_1)
            AllChem.UFFOptimizeMoleculeConfs(mol_baseUFF, numThreads=args.num_threads, maxIters=200)
            mol_baseUFF=Chem.RemoveHs(mol_baseUFF)
            RMSlist_UFF = []
            for c in mol_baseUFF.GetConformers():
                c_id = c.GetId()
                RMS_UFF = AllChem.AlignMol(mol_baseUFF, mol_ref, prbCid=c_id, refCid=0)
                RMSlist_UFF.append(RMS_UFF)
            #AllChem.AlignMolConformers(mol_baseUFF, RMSlist=RMSlist_UFF)
            ttest_uff.extend(RMSlist_UFF)
        except:
            continue

        try:
            ## baseline force field part with MMFF
            mol_baseMMFF = copy.deepcopy(mol_init_1)
            AllChem.MMFFOptimizeMoleculeConfs(mol_baseMMFF, numThreads=args.num_threads, maxIters=200)
            mol_baseMMFF=Chem.RemoveHs(mol_baseMMFF)
            RMSlist_MMFF = []
            for c in mol_baseMMFF.GetConformers():
                c_id = c.GetId()
                RMS_MMFF = AllChem.AlignMol(mol_baseMMFF, mol_ref, prbCid=c_id, refCid=0)
                RMSlist_MMFF.append(RMS_MMFF)
            ttest_mmff.extend(RMSlist_MMFF)
        except:
            continue

        # save results per molecule
        if args.savepermol:
            pkl.dump({'mmff': np.array(ttest_mmff), 'uff': np.array(ttest_uff), 'n_rot_bonds':n_rot_bonds, 'n_heavy_atoms': n_est},\
                    open(os.path.join(dir_name, 'mol_{}.p'.format(t)), 'wb'))

    #print (len(ttest))
    if len(ttest_uff) > 0:
        mean_ttest, std_ttest = np.mean(ttest_uff, 0), np.std(ttest_uff, 0)
        uff.append([mean_ttest, std_ttest, len(ttest_uff)])

    if len(ttest_mmff) > 0:
        mean_ttest, std_ttest = np.mean(ttest_mmff, 0), np.std(ttest_mmff, 0)
        mmff.append([mean_ttest, std_ttest, len(ttest_mmff)])

print ("UFF results")
print (np.mean(np.array(uff)[:,0]), np.mean(np.array(uff)[:,1]))
print ("MMFF results")
print (np.mean(np.array(mmff)[:,0]), np.mean(np.array(mmff)[:,1]))

f_name = args.data + data_split
pkl.dump(np.array(uff), open(os.path.join(args.savedir, f_name + 'uff.p'), 'wb'))
pkl.dump(np.array(mmff), open(os.path.join(args.savedir, f_name + 'mmff.p'), 'wb'))
