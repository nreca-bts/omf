# -*- coding: utf-8 -*-
"""
Run Iowa State PINN-based photovoltaic hosting-capacity analysis routines for MOHCA
workflows.
"""
import numpy as np
import pandas as pd
import os
import random
from pathlib import Path

def PINN_HC(input_csv_path, output_csv_path, nodes_selected=0 ):

    """
    Perform pinn hc processing for the wrapped solver workflow.
    """
    import torch
    import torch.nn as nn
    import torch.utils.data as Data
    from torch.autograd import Variable
    
    """

    Parameters
    ----------
    input_csv_path : str
        the file path of the input data.
    output_csv_path : str
        the file path of the output result data.
    nodes_selected : list, optional
        the selected nodes to calculate LHC. The default is 0, whhich means all the nodes are analyzed.

    Returns
    -------
    the LHC results.

    """
    def set_device():
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        # print('Using device:', device)    
        return device

    def set_seed(seed: int = 42) -> None:
        np.random.seed(seed)
        random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        os.environ["PYTHONHASHSEED"] = str(seed)
        # print(f"Random seed set as {seed}")
        
    device = set_device()
    set_seed()

    def TrainTestSplit(x_data, y_data, perc, node_number):  
        device = set_device()

        splitpoint = round(x_data.shape[0]*perc)
        x_data_train = torch.tensor(x_data[:splitpoint :], dtype=torch.float32).to(device)
        y_data_train = torch.tensor(y_data[:splitpoint :], dtype=torch.float32).to(device)
        x_data_test = torch.tensor(x_data[splitpoint: :], dtype=torch.float32).to(device)
        y_data_test = torch.tensor(y_data[splitpoint: :], dtype=torch.float32).to(device) 
        
        x_data_train_P_xf = (x_data_train[:,:node_number] - x_data_train[:,:node_number].mean())/ x_data_train[:,:node_number].std()
        x_data_train_Q_xf = (x_data_train[:,node_number:] - x_data_train[:,node_number:].mean())/ x_data_train[:,node_number:].std()
        
        y_data_train_xf = (y_data_train - y_data_train.mean())/ y_data_train.std()  
        x_data_train_xf = torch.concat((x_data_train_P_xf, x_data_train_Q_xf), axis=1)

        
        x_data_test_P_xf = (x_data_test[:,:node_number] - x_data_train[:,:node_number].mean())/ x_data_train[:,:node_number].std()
        x_data_test_Q_xf = (x_data_test[:,node_number:] - x_data_train[:,node_number:].mean())/ x_data_train[:,node_number:].std()
        
        x_data_test_xf = torch.concat((x_data_test_P_xf, x_data_test_Q_xf), axis=1)

        x_reverse_P_xf_mean = torch.ones(node_number, dtype=torch.float32).to(device)
        x_reverse_P_xf_std = torch.ones(node_number, dtype=torch.float32).to(device)
        x_reverse_P_xf_mean = x_reverse_P_xf_mean*x_data_train[:,:node_number].mean()
        x_reverse_P_xf_std = x_reverse_P_xf_std*x_data_train[:,:node_number].std() 

        x_reverse_Q_xf_mean = torch.ones(node_number, dtype=torch.float32).to(device)
        x_reverse_Q_xf_std = torch.ones(node_number, dtype=torch.float32).to(device)
        x_reverse_Q_xf_mean = x_reverse_Q_xf_mean*x_data_train[:,node_number:].mean()
        x_reverse_Q_xf_std = x_reverse_Q_xf_std*x_data_train[:,node_number:].std() 
        

        x_reverse_xf_mean = torch.concat((x_reverse_P_xf_mean, x_reverse_Q_xf_mean))
        x_reverse_xf_std = torch.concat((x_reverse_P_xf_std, x_reverse_Q_xf_std))

        
        y_reverse_xf_mean = torch.ones(node_number, dtype=torch.float32).to(device)
        y_reverse_xf_std = torch.ones(node_number, dtype=torch.float32).to(device)
        

        y_reverse_xf_mean = y_reverse_xf_mean*y_data_train[:,:node_number].mean()
        y_reverse_xf_std = y_reverse_xf_std*y_data_train[:,:node_number].std() 
        
        return x_data_train_xf, \
            y_data_train_xf, \
            x_data_test_xf, \
            y_data_test, \
            y_reverse_xf_mean,\
            y_reverse_xf_std,\
            x_reverse_xf_mean,\
            x_reverse_xf_std 
            

    
    def model_selection(model_name, node_number):
        '''
        Parameters
        ----------
        model_name : char
            Select specific model for the voltage calculation
        node_number : int
            Enter the nodenumber as the customer number
        Returns
        -------
        Return initialized model

        '''
            
        class Linearlize_totalpower_OLTC_Net(nn.Module):
            
            def __init__(self, node_number):
                """
                Internal helper for isu pinnbased hca init processing.
                """
                super(Linearlize_totalpower_OLTC_Net, self).__init__()   
                
                self.node_number = node_number
                self.A = nn.Linear(node_number, node_number, bias=False)
                self.A.weight = torch.nn.Parameter(torch.from_numpy(np.identity(node_number)))# initialize the weight of B layer      
                self.B = nn.Linear(node_number, node_number, bias=False)  
                self.B.weight = torch.nn.Parameter(torch.from_numpy(np.identity(node_number)))# initialize the weight for test    
                self.K =  Variable(torch.randn(1, node_number).type(dtype=torch.float32), requires_grad=True).to(device)   
                
                self.Layer1 = nn.Linear(3*node_number, 2*node_number, bias=True)
                self.Layer1.weight = torch.nn.Parameter(torch.from_numpy(np.zeros( (2*node_number, node_number*3) ))) 
                self.Layer2 = nn.Linear(2*node_number, node_number, bias=True)
                self.Layer2.weight = torch.nn.Parameter(torch.from_numpy(np.zeros( (node_number, node_number*2))))
                
                self.AF1 = nn.Sigmoid()
                self.AF2 = nn.LeakyReLU(0.2)
                self.AF3 = nn.ReLU()
                self.AF4 = nn.Tanh()
                
                
                self.Total_load_adjust1 = nn.Linear(2*node_number + 2, 2*node_number, bias=True)
                self.Total_load_adjust2 = nn.Linear(2*node_number, node_number, bias=True)
                self.Total_load_adjust1.weight = torch.nn.Parameter(torch.from_numpy(np.zeros( (2*node_number , 2*node_number +2))))
                self.Total_load_adjust2.weight = torch.nn.Parameter(torch.from_numpy(np.zeros( (node_number, 2*node_number))))
        
        
                self.Combine = nn.Linear(node_number, node_number, bias=True)
                self.Combine.weight = torch.nn.Parameter(torch.from_numpy( np.identity(node_number)  ) )# initialize the weight for test 
                # self.Combine.bias = torch.nn.Parameter(torch.from_numpy(  np.random.rand(node_number).reshape((node_number,1))   ) )# initialize the weight for test 
                
                self.dropout = nn.Dropout(0.25)
                
                for name, p in self.Combine.named_parameters():
                    if name=='weight':
                        p.requires_grad=False  
        
            def forward(self, x): 
                """
                Implement forward behavior for Linearlize_totalpower_OLTC_Net instances.
                """
                xp = self.A(x[:,:self.node_number])
                xq = self.B(x[:,self.node_number:])
                
                xpq = xp + xq
        
                v = self.Combine(xpq)
                
                x_2 = torch.pow(x, 2)
                xpqv = torch.concat((x_2, v), dim=1)
                xpqv = self.Layer1(xpqv)
                xpqv = self.AF4(xpqv)
                xpqv = self.Layer2(xpqv)
                xpqv = self.AF4(xpqv)
                
                v_final = xpqv + v
                xp_sum = torch.reshape(torch.sum(xp, axis = 1), (-1,1))
                xq_sum = torch.reshape(torch.sum(xq, axis = 1), (-1,1))
                  
                total_pqv = torch.concat((xp_sum, xq_sum, xp, xq), dim=1)
                total_pqv = self.Total_load_adjust1(total_pqv)
                total_pqv = self.AF4(total_pqv)
                total_pqv = self.Total_load_adjust2(total_pqv)
                total_pqv = self.AF4(total_pqv)
                
                total_pqv_final = v_final + total_pqv
                
                
                return total_pqv_final, xpqv, total_pqv,v


        model = Linearlize_totalpower_OLTC_Net(node_number).float().to(device)

        return model
    
    # ********************************************************************************
    #                     Data loading and formating
    # ********************************************************************************
    batch_size = 200 # batch size for model training
    node_number = 50 # Customer number
    data = pd.read_csv(input_csv_path)
    P = np.array(data['kw_reading']).reshape(node_number,-1).T
    Q = np.array(data['kvar_reading']).reshape(node_number,-1).T
    PQ = np.hstack((P, Q))
    PQ_data = PQ
    
    V = np.array(data['v_reading']).reshape(node_number,-1).T
    v_base = 120
    V = V / v_base # convert to Per Unit Value
    V = np.power(V, 2)
    V_data = V
    
    x_data_train_xf, y_data_train_xf, x_data_test_xf, y_data_test, y_reverse_xf_mean, y_reverse_xf_std, x_reverse_xf_mean,x_reverse_xf_std = TrainTestSplit(PQ_data, V_data, 1, node_number)
    torch_dataset = Data.TensorDataset(x_data_train_xf, y_data_train_xf)
    
    loader_train = Data.DataLoader( 
        dataset=torch_dataset,  # torch TensorDataset format
        batch_size=batch_size,  # mini batch size
        shuffle=False,  #
        )
    
    
    # torch_dataset_test = Data.TensorDataset(x_data_test_xf, y_data_test)
    
    
    # loader_test = Data.DataLoader(
    #     dataset=torch_dataset_test,  # torch TensorDataset format
    #     batch_size=batch_size,  # mini batch size
    #     shuffle=False,  
    #     )
    
    # ********************************************************************************
    #                     Model Building an Training
    # ********************************************************************************
    
    model = model_selection('Linearlize_totalpower_Net', node_number)
      
    actual_test_results = []
    predict_test_results = []
    # actual_train_results = []
    # predict_train_results = []
    loss_func = nn.MSELoss()
    epoch_parameter = 3000
    Beta = 0.0005
    regularization_type = 'L'
    #------------Adaptive Learning Rate---------------
    optimizer = torch.optim.SGD(model.parameters(), lr=0.5, momentum=0.01)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda=lambda epoch:0.95**(epoch//200))
    Epoch_loss_record = []

    
    
    for i in range(epoch_parameter):
        running_loss = 0.0
        running_regular = 0.0
        loss_view = 0.0    
        # print("| Learning Rate in Epoch {0} ： {1:4.2f}|".format(i, optimizer.param_groups[0]['lr']))
        
        for step, (batch_x, batch_y) in enumerate(loader_train):
            
            out, linearlize_error_comp, uplevel_voltage_influence, v= model(batch_x)
            
       
            if regularization_type == 'L':
                # A weight 
                A_weight = torch.norm(model.A.weight, 2)
                A_w = torch.norm(model.A.weight, 1)
                # B weight
                B_weight = torch.norm(model.B.weight, 2)
                B_w = torch.norm(model.B.weight, 1)
                # linearlize_error_comp
                error_comp = torch.norm(linearlize_error_comp, 2)
                # uplevel_voltage_influence
                voltage_influence = torch.norm(uplevel_voltage_influence, 2)
                # keep A and B positive
                
                keep_positive = torch.abs(-model.A.weight.sum() - torch.norm(model.A.weight, 1)) + torch.abs(-model.B.weight.sum() - torch.norm(model.B.weight, 1))
                
                regularization_loss = Beta*( A_weight + 0.00*A_w + B_weight + 0.00*B_w + 0.1*error_comp + 0*voltage_influence + 0.1*keep_positive)
           
                regularization_loss = regularization_loss.cpu()
                
            elif regularization_type == 'No':
                 
                 regularization_loss = 0
                
    
            loss = loss_func(out,batch_y) + regularization_loss + 0.5*loss_func(v,batch_y)
            optimizer.zero_grad()                     
            loss.backward()  
    
            
            temp_A = (model.A.weight.grad.clone() + model.A.weight.grad.clone().T)/2
            model.A.weight.grad = nn.Parameter(temp_A)
            temp_B = (model.B.weight.grad.clone() + model.B.weight.grad.clone().T)/2
            model.B.weight.grad = nn.Parameter(temp_B)
            
            optimizer.step()
            running_loss += loss.item()
            running_regular = running_regular + regularization_loss
            loss_view += loss.item()
    
        scheduler.step()
        
                
        # print('| Epoch:{} | Sum_Loss:{:.5f} | Reg:{:5.2f} | Loss:{:5.2f} |'.format(i+1, loss_view, running_regular, loss_view-running_regular))
        Epoch_loss_record.append(loss_view)
    
    # Modified
    modelDir = output_csv_path.parent
    filepath =  Path(modelDir, 'Pysical_Model.pt')
    torch.save(model.state_dict(), filepath)  
    
    
    # ********************************************************************************
    #                     Locational Hosting Capacity Analysis
    # ********************************************************************************
    # 1Day 1Node Hosting Capacity
    PQ_extreme_all = PQ_data
    V_extreme_all = V_data
    PQ_extreme_record = PQ_extreme_all.copy()
    
    
    if nodes_selected == 0:
        selectednodes = [i for i in range(node_number)]
    else:
        selectednodes = nodes_selected
    
    
    PV_capacity_record_all_nodes = pd.DataFrame({'busname':[], 'kW_hostable': []})
    for node in selectednodes:
        
        PV_capacity_record = []
        select_node = node + 1
        # print('/========= Calculating Node {0} Results =========/'.format(select_node))
        for i in range(V_extreme_all.shape[0]):
            PQ_extreme = PQ_extreme_all[i:i+1,:].copy()
            V_extreme = V_extreme_all[i,:].copy()
            # PQ_original = 
            detlaP = 0.5
            V_constrain = 0
        
            voltage_record = []
            P_target = PQ_extreme[0,select_node-1]
            V = 0
            while V_constrain < 0.05:
                P_target = P_target - detlaP
                PQ_extreme[0,select_node-1] = P_target
                x_data_test_extreme = torch.tensor(PQ_extreme, dtype=torch.float32).to(device)
                x_data_test_xf_extreme = (x_data_test_extreme - x_reverse_xf_mean.to(device)) / x_reverse_xf_std.to(device)
                
                torch_extreme_dataset = Data.TensorDataset(x_data_test_xf_extreme)
                extreme_dataloader = Data.DataLoader(
                    dataset=torch_extreme_dataset,  # torch TensorDataset format
                    batch_size=batch_size,  # mini batch size
                    shuffle=False,  #
                    )
                actual_test_results = []
                predict_test_results = []
            
                with torch.no_grad():
                    for step, batch_x in enumerate(extreme_dataloader):
                        batch_x_data = batch_x[0].to(device)
                        predict,xpqv, total_pqv,v = model(batch_x_data)
                        predict = predict*y_reverse_xf_std.to(device) + y_reverse_xf_mean.to(device)
                        predict_test_results = predict_test_results + predict.reshape(-1).tolist()
                        
    
                    V_constrain = (np.power(np.array(predict_test_results),0.5)-1).max()
                    V_location = np.where((np.power(np.array(predict_test_results),0.5)-1) == V_constrain)
                    V = np.power(np.array(predict.cpu()),0.5)[0,select_node-1]
            
            PV_capacity = PQ_extreme_record[i, select_node-1] - P_target
            PV_capacity_record.append(PV_capacity)            
            # print('/========= Extreme Case {0} Results at time point {1}=========/'.format(select_node, i ))    
            # print('|  V_location: {:3d}  | Max PV Capacity for {:3d} is {:5.4f}  |'.format(V_location[0][0]+1, select_node, PV_capacity))
        node_temp = pd.DataFrame({'busname':['bus'+str(node+1)], 'kW_hostable': min(PV_capacity_record)})
        PV_capacity_record_all_nodes = pd.concat([PV_capacity_record_all_nodes, node_temp]).reset_index(drop=True)

    
    return ( PV_capacity_record_all_nodes, PV_capacity_record_all_nodes.to_csv(output_csv_path, index=None) )


def sanity_check():
    """
    Perform sanity check processing for the wrapped solver workflow.
    """
    pass