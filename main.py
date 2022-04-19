import math, random, argparse, time, uuid
import os, os.path as osp
# from helper import makeDirectory, set_gpu

import numpy as np
import torch
from torch.nn import functional as F
from sklearn.model_selection import KFold
from torch_geometric.loader import DataLoader, DenseDataLoader as DenseLoader
from torch_geometric.datasets import TUDataset
from MyModel import MyModel


def makeDirectory(dirpath):
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)


def set_gpu(gpus):
    if torch.cuda.is_available():
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        # os.environ["CUDA_VISIBLE_DEVICES"] = gpus
        torch.cuda.set_device(1)


# 禁止网络加速
torch.backends.cudnn.benchmark = False


class Trainer(object):

    def __init__(self, params, seed):
        self.p = params
        self.seed = seed
        # set GPU
        if self.p.gpu != '-1' and torch.cuda.is_available():
            self.device = torch.device('cuda')
            torch.cuda.set_rng_state(torch.cuda.get_rng_state())
            torch.backends.cudnn.deterministic = True
        else:
            self.device = torch.device('cpu')

        # build the data
        self.p.use_node_attr = (self.p.dataset == 'FRANKENSTEIN')
        self.dataset = self.loadData()

        # build the model
        self.model = None
        self.optimizer = None


    # load data
    def loadData(self):
        # path = osp.join(osp.dirname(osp.realpath(__file__)), '.', 'data', self.p.dataset)
        path = "../data/" + self.p.dataset
        dataset = TUDataset(path, self.p.dataset, use_node_attr=self.p.use_node_attr)
        dataset.data.edge_attr = None
        # self.data = dataset
        return dataset

    # load model
    def addModel(self):
        # if self.p.model == 'ASAP_Pool':
        #     model = ASAP_Pool(
        #         dataset=self.data,
        #         num_layers=self.p.num_layers,
        #         hidden=self.p.hid_dim,
        #         ratio=self.p.ratio,
        #         dropout_att=self.p.dropout_att,
        #     )
        if self.p.model == 'GCN':
            model = GCN(dataset=self.dataset, hidden=32,  dropout_att=0.5)
        else:
            raise NotImplementedError
        model.to(self.device).reset_parameters()
        return model

    def addOptimizer(self):
        return torch.optim.Adam(self.model.parameters(), lr=self.p.lr, weight_decay=self.p.l2)

    # train model for an epoch
    def run_epoch(self, loader):
        self.model.train()

        total_loss = 0
        correct = 0
        # loader中有7个batch， 前6个batch中分别有128个graph
        for data in loader:
            self.optimizer.zero_grad()
            data = data.to(self.device)
            # shape of ground_truth: (batch)
            ground_truth = data.y.clone()
            # shape of out: (batch, num_target)
            out = self.model(data)
            # 对一个graph上的平均 loss进行回传
            loss = F.nll_loss(out, ground_truth.view(-1))
            loss.backward()
            # self.num_graphs 返回每个batch（data）中有多少个graph
            # 所以这个loss应该是单个graph的loss
            total_loss += loss.item() * self.num_graphs(data)
            pred = out.max(1)[1]
            correct += pred.eq(ground_truth.view(-1)).sum().item()
            self.optimizer.step()
        # 返回的loss是所有graph上loss 的平均值
        return correct/len(loader.dataset), total_loss / len(loader.dataset)

    # validate or test model
    def predict(self, loader):
        self.model.eval()

        correct = 0
        for data in loader:
            data = data.to(self.device)
            with torch.no_grad():
                pred = self.model(data).max(1)[1]
            correct += pred.eq(data.y.view(-1)).sum().item()
        test_acc = correct / len(loader.dataset)
        # print(f"seed/fold {seed}/{fold}  test_acc: {test_acc:.4f}")
        return test_acc

    # save model locally
    def save_model(self, save_path):
        state = {
            'state_dict': self.model.state_dict(),
            'optimizer': self.optimizer.state_dict(),
            'args': vars(self.p)
        }
        torch.save(state, save_path)

    # load model from path
    # Q: 这部分加载训练好的模型和优化器的代码还没有遇到过
    def load_model(self, load_path):
        state = torch.load(load_path)
        self.model.load_state_dict(state['state_dict'])
        self.optimizer.load_state_dict(state['optimizer'])

    # use 10 fold cross-validation
    def k_fold(self):
        # 训练集合和测试集不同
        kf = KFold(self.p.folds, shuffle=True, random_state=self.p.seed)

        test_indices, train_indices = [], []
        for _, idx in kf.split(torch.zeros(len(self.dataset)), self.dataset.data.y):
            # 添加每一折的测试集
            test_indices.append(torch.from_numpy(idx).long())

        # 循环交错取出test_indices中的items 作为验证集
        val_indices = [test_indices[i - 1] for i in range(self.p.folds)]

        for i in range(self.p.folds):
            train_mask = torch.ones(len(self.dataset), dtype=torch.long)
            train_mask[test_indices[i].long()] = 0
            train_mask[val_indices[i].long()] = 0
            train_indices.append(train_mask.nonzero().view(-1))
        return train_indices, test_indices, val_indices

    def num_graphs(self, data):
        if data.batch is not None:
            return data.num_graphs
        else:
            return data.x.size(0)

    # main function for running the experiments
    def run(self):
        val_accs, test_accs = [], []

        makeDirectory('torch_saved/')
        self.p.name = self.p.name.replace(":", "_")
        save_path = 'torch_saved/{}'.format(self.p.name)
        # 如果在命令行中运行，且有参数 restore, 则会直接加载模型
        if self.p.restore:
            self.load_model(save_path)
            print('Successfully Loaded previous model: ')
            print(f'{save_path}')

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        # iterate over 10 folds
        # 重组训练集、测试集、验证集
        # self.k_fold函数返回的形式是这样的： ([train_indices, test_indices, val_indeices)
        for fold, (train_idx, test_idx, val_idx) in enumerate(zip(*self.k_fold())):

            # Reinitialise model and optimizer for each fold
            self.model = self.addModel()
            self.optimizer = self.addOptimizer()


            train_dataset = self.dataset[train_idx]
            # print(f"test_idx {test_idx}")
            test_dataset = self.dataset[test_idx]
            val_dataset = self.dataset[val_idx]
            # print(f"train_dataset {train_dataset}")
            # print(f"train_dataset[0] {train_dataset[0]}")
            # print(f"adj in train_dataset[0] {'adj' in train_dataset[0]}")
            if 'adj' in train_dataset[0]:
                train_loader = DenseLoader(train_dataset, self.p.batch_size, shuffle=True)
                val_loader = DenseLoader(val_dataset, self.p.batch_size, shuffle=False)
                test_loader = DenseLoader(test_dataset, self.p.batch_size, shuffle=False)
            else:
                # 用dataloader加载数据
                # 每128个图组成一个batch
                train_loader = DataLoader(train_dataset, self.p.batch_size, shuffle=True)
                val_loader = DataLoader(val_dataset, self.p.batch_size, shuffle=False)
                test_loader = DataLoader(test_dataset, self.p.batch_size, shuffle=False)

            if torch.cuda.is_available():
                torch.cuda.synchronize()

            # 每个epoch中的最佳验证和测试精度
            best_val_acc, best_test_acc = 0.0, 0.0

            # 对于每折数据，训练max_epochs个epoch
            for epoch in range(1, self.p.max_epochs + 1):
                train_acc, train_loss = self.run_epoch(train_loader)
                val_acc = self.predict(val_loader)

                # lr_decay 每50个epoch, 模型学习率衰减为原来1半
                if epoch % self.p.lr_decay_step == 0:
                    for param_group in self.optimizer.param_groups:
                        param_group['lr'] = self.p.lr_decay_factor * param_group['lr']
                # save model for best val score
                # 根据每个epoch的结果寻找最好的验证集上的精度，但是验证集精度下降的时候，并不会终止模型的训练
                if val_acc > best_val_acc:
                    best_val_acc = val_acc
                    self.save_model(save_path)

                print('seed/fold/epoch {}/{:02d}/{:03d}:  Train_Loss: {:.4f}\tTrain_Acc {:.4f}\tVal Acc: {:.4f}'
                                                                                                .format(self.seed,
                                                                                                        fold + 1,
                                                                                                        epoch,
                                                                                                        train_loss,
                                                                                                        train_acc,
                                                                                                        best_val_acc))

            # load best model for testing
            # 对于每一个seed的每一个数据划分，找到其在验证集精度上最高的从模型参数
            self.load_model(save_path)
            # 对于每一个seed的每一个数据划分，选取验证集上最好的精度，然后在测试集上进行测试
            # seed|fold test_acc
            best_test_acc = self.predict(test_loader)
            print('seed/fold/{:02d}/{:03d}:  Train_Loss: {:.4f}  \tTrain_Acc {:.2f}  \tVal Acc: {:.2f}  '
                  '\tTest Acc: {:.2f}'
                  .format(self.seed,
                          fold + 1,
                          train_loss,
                          train_acc,
                          best_val_acc,
                          best_test_acc))

            if torch.cuda.is_available():
                torch.cuda.synchronize()

            # 对于每一个seed的每一折数据划分，在其所有的epoch中，将验证集上最佳精度和因此选择的测试集精度保存在列表中
            # 对于每一个seed共有10个最佳验证集精度和凭借此模型测试出的测试精度
            val_accs.append(best_val_acc)
            test_accs.append(best_test_acc)

        # 对于每一个seed，将所有数据划分上的最佳验证精度和产生此最佳验证精度的模型在测试集合上的精度取平均，得到每个seed上的平均精度
        val_acc_mean = np.round(np.mean(val_accs), 4)
        test_acc_mean = np.round(np.mean(test_accs), 4)
        print(f"seed {self.seed}  val_acc_mean {val_acc_mean:.4f}  test_acc_mean {test_acc_mean:.4f}")
        return val_acc_mean, test_acc_mean


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Neural Network Trainer Template')
    parser.add_argument('-model', dest='model', default='GCN', help='Model to use')
    parser.add_argument('-data', dest='dataset', default='PROTEINS', type=str, help='Dataset to use')
    parser.add_argument('-epoch', dest='max_epochs', default=100, type=int, help='Max epochs')
    parser.add_argument('-l2', dest='l2', default=5e-4, type=float, help='L2 regularization')
    parser.add_argument('-num_layers', dest='num_layers', default=3, type=int, help='Number of GCN Layers')
    parser.add_argument('-lr_decay_step', dest='lr_decay_step', default=50, type=int, help='lr decay step')
    parser.add_argument('-lr_decay_factor', dest='lr_decay_factor', default=0.5, type=float, help='lr decay factor')

    parser.add_argument('-batch', dest='batch_size', default=128, type=int, help='Batch size')
    parser.add_argument('-hid_dim', dest='hid_dim', default=128, type=int, help='hidden dims')
    parser.add_argument('-dropout_att', dest='dropout_att', default=0.1, type=float, help='dropout on attention scores')
    parser.add_argument('-lr', dest='lr', default=0.01, type=float, help='Learning rate')
    parser.add_argument('-ratio', dest='ratio', default=0.5, type=float, help='ratio')

    parser.add_argument('-folds', dest='folds', default=10, type=int, help='Cross validation folds')

    parser.add_argument('-name', dest='name', default='test_' + str(uuid.uuid4())[:8], help='Name of the run')
    parser.add_argument('-gpu', dest='gpu', default='1', help='GPU to use')
    parser.add_argument('-restore', dest='restore', action='store_true', help='Model restoring')

    args = parser.parse_args()
    # 如果在命令行中写了参数 restore， 则会出发restore--action=True, 则不会重设args.name
    # 而如果在命令行中没有写参数restore，则不触发restore--action=False，之后便会重设args.name
    if not args.restore:
        args.name = args.name + '_' + time.strftime('%d_%m_%Y') + '_' + time.strftime('%H:%M:%S')

    print('Starting runs...')
    print(args)
    # get 20 run average
    # seeds = [8971, 85688, 9467, 32830, 28689, 94845, 69840, 50883, 74177, 79585, 1055, 75631, 6825, 93188, 95426, 54514, 31467, 70597, 71149, 81994]
    seeds = [8971, 85688, 9467, 32830, 28689, 94845, 69840, 50883, 74177, 79585]
    counter = 0
    args.log_db = args.name
    print("log_db:", args.log_db)
    avg_val = []
    avg_test = []
    for seed in seeds:
        # set seed
        args.seed = seed
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        set_gpu(args.gpu)

        args.name = '{}_run_{}'.format(args.log_db, counter)

        # start training the model
        model = Trainer(args, seed)
        # 获得每一个seed上，每一折上，最佳验证精度和测试精度的平均
        val_acc, test_acc = model.run()
        print('For seed {}\t Val Accuracy: {:.3f} \t Test Accuracy: {:.3f}\n'.format(seed, val_acc, test_acc))
        avg_val.append(val_acc)
        avg_test.append(test_acc)
        counter += 1
    # 将所有seed上的验证精度和测试精度取平均和标准差
    print('Val Accuracy: {:.3f} ± {:.3f} Test Accuracy: {:.3f} ± {:.3f}'.format(np.mean(avg_val), np.std(avg_val),
                                                                                np.mean(avg_test), np.std(avg_test)))