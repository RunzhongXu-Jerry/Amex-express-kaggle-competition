# -*- coding: utf-8 -*-
"""feature_preprocess.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/11MJj4GKrWhI8FGwMiKXXosGRI84Ac1Xl
"""

import gc
import os
import joblib
import random
import warnings
import itertools
import scipy as sp
import numpy as np
import pandas as pd
from tqdm import tqdm
import lightgbm as lgb
from itertools import combinations
pd.set_option('display.width', 1000)
pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
from sklearn.preprocessing import LabelEncoder
import warnings; warnings.filterwarnings('ignore')
from sklearn.model_selection import StratifiedKFold, train_test_split

class CFG:
  seed = 42
  INPUT = "../data/amex-data-integer-dtypes-parquet-format"
  TRAIN = True 
  INFER = True
  n_folds = 5
  target ='target'
  DEBUG= True 
  ADD_CAT = True
  ADD_LAG = True 
  ADD_DIFF =  [1, 2]
  ADD_MIDDLE = True
  output_dir = "../data"

def seed_everything(seed):
  random.seed(seed)
  np.random.seed(seed)
  os.environ['PYTHONHASHSEED']=str(seed)

seed_everything(CFG.seed)

# Feature Engineering on credit risk
spend_p=[ 'S_3',  'S_5', 'S_6', 'S_7', 'S_8', 'S_9', 'S_11', 'S_12', 'S_13', 'S_15', 'S_16', 'S_17', 'S_18', 'S_19', 'S_20', 'S_22', 'S_23', 'S_24', 'S_25', 'S_26', 'S_27']
balance_p = ['B_1', 'B_2', 'B_3',  'B_5', 'B_6', 'B_7', 'B_8', 'B_9', 'B_10', 'B_11', 'B_12', 'B_13', 'B_14', 'B_15',  'B_17', 'B_18',  'B_21',   'B_23', 'B_24', 'B_25', 'B_26', 'B_27', 'B_28',  'B_36', 'B_37',  'B_40']
payment_p = ['P_2', 'P_3', 'P_4']

def process_data(df):
  features = df.drop(['customer_ID','S_2','D_103','D_139'], axis = 1).columns.to_list()
  cat_features = [
        "B_30",
        "B_38",
        "D_114",
        "D_116",
        "D_117",
        "D_120",
        "D_126",
        "D_63",
        "D_64",
        "D_66",
        "D_68",
    ]
  num_features = [col for col in features if col not in cat_features]
  num_agg = df.groupby("customer_ID")[num_features].agg(['first', 'mean', 'std', 'min', 'max', 'last'])
  num_agg.columns = ['_'.join(x) for x in num_agg.columns]
  num_agg.reset_index(inplace = True)

  num_agg["P2B9"] = df["P_2"] / df["B_9"]
  
  # calculate the diff between max and min
  # calculate the diff between each col and mean value
  for ncol in num_agg:
    if ncol+"_mean" in num_agg.columns:
      num_agg[f'{ncol}-mean'] = num_agg[ncol] - num_agg[ncol+"_mean"]
      num_agg[f'{ncol}-div-mean'] = num_agg[ncol] - num_agg[ncol+"_mean"]
    if (ncol+"_min" in df.columns) and (ncol+"_max" in df.columns):
      num_agg[f'{ncol}_min_div_max'] = num_agg[ncol+"_min"]/num_agg[ncol+"_max"]
      num_agg[f'{ncol}_max_diff_min'] = num_agg[ncol+"_max"]-num_agg[ncol+"_min"]

  
  # lag features
  for col in num_agg:
    for col_2 in ['first','mean','std','min','max']:
      if 'last' in col and col.replace('last', 'first') in num_agg:
        num_agg[col + col_2 + '_lag_sub'] = num_agg[col+col_2] - num_agg[col.replace('last', 'first')]
        num_agg[col + col_2 + '_lag_div'] = num_agg[col+col_2] / num_agg[col.replace('last', 'first')]

  cat_agg = df.groupby("customer_ID")[cat_features].agg(['count', 'first', 'last', 'nunique'])
  cat_agg.columns = ['_'.join(x) for x in cat_agg.columns]
  cat_agg.reset_index(inplace = True)

  cols = list(num_agg.dtypes[num_agg.dtypes == 'float64'].index)
  for col in tqdm(cols):
    num_agg[col] = num_agg[col].astype(np.float32)
  # Transform int64 columns to int32
  cols = list(cat_agg.dtypes[cat_agg.dtypes == 'int64'].index)
  for col in tqdm(cols):
    cat_agg[col] = cat_agg[col].astype(np.int32)
  
  df_diff = get_difference(df,num_features)
  
  # Add sundays count as a feature
  s2_count = df[df.S_2.dt.dayofweek==6].groupby("customer_ID")
  s2_count.columns = ['S_2_Sun_Count']
  s2_count.reset_index(inplace=True)

  # The diff between sum
  num_agg["P_sum"] = df[payment_p].sum(axis=1)
  num_agg["S_sum"] = df[spend_p].sum(axis=1)
  num_agg["B_sum"] = df[balance_p].sum(axis=1)
  num_agg["P-S"] = num_agg.P_sum - num_agg.S_sum
  num_agg["P-B"] = num_agg.P_sum - num_agg.B_sum
  num_agg = num_agg.drop(["S_sum","P_sum","B_sum"],axis=1)


  df = num_agg.merge(cat_agg, how = 'inner', on = 'customer_ID').merge(df_diff, how = 'inner', on = 'customer_ID')
  del train_num_agg, train_cat_agg, train_diff
  gc.collect()
  return df

def get_difference(data, num_features):
  df1 = []
  customer_ids = []
  for customer_id, df in tqdm(data.groupby(['customer_ID'])):
      diff_df1 = df[num_features].diff(axis=1).iloc[[-1]].values.astype(np.float32)
      df1.append(diff_df1)
      customer_ids.append(customer_id)
  df1 = np.concatenate(df1, axis = 0)
  df1 = pd.DataFrame(df1, columns = [col + '_diff1' for col in df[num_features].columns])
  df1['customer_ID'] = customer_ids
  return df1

train = pd.read_parquet('./train.parquet')
train = process_data(train)
train_labels = pd.read_csv('./train_labels.csv')
train = train.merge(train_labels,how='inner',on='customer_ID')
test = pd.read_parquet('./test.parquet')
test = process_data(test)

train.to_pickle('train_fe_v1.pickle')
test.to_pickle('test_fe_v1.pickle')







