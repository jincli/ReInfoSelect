import argparse

import torch
from torch import nn
from torch.autograd import Variable
from torch.distributions import Categorical

from policy import all_policy
from dataloaders import *
from models import cknrm
from metrics import *

def dev(args, model, dev_data, device):
    features = []
    rst_dict = {}
    for s, batch in enumerate(dev_data):
        query_id = batch[0]
        doc_id = batch[1]
        qd_score = batch[2]
        batch = tuple(t.to(device) for t in batch[3:])
        (raw_score, query_idx, doc_idx, query_len, doc_len) = batch

        with torch.no_grad():
            doc_scores, doc_features = model(query_idx, doc_idx, query_len, doc_len, raw_score)
        d_scores = doc_scores.detach().cpu().tolist()
        d_features = doc_features.detach().cpu().tolist()

        for (q_id, d_id, qd_s, d_s, d_f) in zip(query_id, doc_id, qd_score, d_scores, d_features):
            feature = []
            feature.append(str(qd_s))
            feature.append('id:' + q_id)
            for i, fi in enumerate(d_f):
                feature.append(str(i+1) + ':' + str(fi))
            features.append(' '.join(feature))
            if q_id in rst_dict:
                rst_dict[q_id].append((qd_s, d_s, d_id))
            else:
                rst_dict[q_id] = [(qd_s, d_s, d_id)]

    with open(args.res, 'w') as writer:
        for q_id, scores in rst_dict.items():
            res = sorted(scores, key=lambda x: x[1], reverse=True)
            for rank, value in enumerate(res):
                writer.write(q_id+' '+'Q0'+' '+str(value[2])+' '+str(rank+1)+' '+str(value[1])+' Conv-KNRM\n')

    ndcg = cal_ndcg(args.qrels, args.res, args.depth)
    return ndcg, features

def train(args, policy, p_optim, model, m_optim, crit, word2vec, dev_data, device):
    best_ndcg = 0.0
    for ep in range(args.epoch):
        # train data
        train_data = train_dataloader(args, word2vec)
        ndcg, features = dev(args, model, dev_data, device)
        print('init_ndcg: ' + str(ndcg))
        if ndcg > best_ndcg:
            best_ndcg = ndcg
            with open(args.res_f, 'w') as writer:
                for feature in features:
                    writer.write(feature+'\n')
        last_ndcg = ndcg

        log_prob_ps = []
        log_prob_ns = []
        log_probs = []
        rewards = []
        for step, batch in enumerate(train_data):
            # select action
            batch = tuple(t.to(device) for t in batch)
            (query_idx, pos_idx, neg_idx, query_len, pos_len, neg_len) = batch

            probs = policy(query_idx, pos_idx, query_len, pos_len)
            dist  = Categorical(probs)
            action = dist.sample()
            if action.sum().item() < 1 and step % args.T != 0:
                continue

            mask = action.ge(0.5)
            weights = Variable(action, requires_grad=False).float().cuda()
            log_prob_p = dist.log_prob(action)
            log_prob_n = dist.log_prob(1-action)
            log_prob_ps.append(torch.masked_select(log_prob_p, mask))
            log_prob_ns.append(torch.masked_select(log_prob_n, mask))

            p_scores, _ = model(query_idx, pos_idx, query_len, pos_len)
            n_scores, _ = model(query_idx, neg_idx, query_len, neg_len)
            label = torch.ones(p_scores.size()).to(device)
            batch_loss = crit(p_scores, n_scores, Variable(label, requires_grad=False))
            batch_loss = batch_loss.mul(weights).mean()
            batch_loss.backward()
            m_optim.step()
            m_optim.zero_grad()

            ndcg, features = dev(args, model, dev_data, device)
            print('epoch: ' + str(ep+1) + ', step: ' + str(step+1) + ', ndcg: ' + str(last_ndcg) + ', best_ndcg: ' + str(best_ndcg))
            if ndcg > best_ndcg:
                best_ndcg = ndcg
                with open(args.res_f, 'w') as writer:
                    for feature in features:
                        writer.write(feature+'\n')
            reward = ndcg - last_ndcg
            last_ndcg = ndcg
            rewards.append(reward)

            if len(rewards) > 0 and step % args.T == 0:
                R = 0.0
                policy_loss = []
                returns = []
                for ri in reversed(range(len(rewards))):
                    R = rewards[ri] + args.gamma * R
                    if R > 0:
                        log_probs.insert(0, log_prob_ps[ri])
                        returns.insert(0, R)
                    else:
                        log_probs.insert(0, log_prob_ns[ri])
                        returns.insert(0, -R)
                for lp, r in zip(log_probs, returns):
                    policy_loss.append((-lp * r).sum().unsqueeze(-1))
                loss = torch.cat(policy_loss).sum()
                loss.backward()
                p_optim.step()
                p_optim.zero_grad()

                log_prob_ps = []
                log_prob_ns = []
                log_probs = []
                rewards = []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-mode', type=str, default='train')
    parser.add_argument('-checkpoint', type=str, default=None)
    parser.add_argument('-train', type=str, default='../data/triples.train.small.tsv')
    parser.add_argument('-dev', type=str, default='../data/dev_toy.tsv')
    parser.add_argument('-qrels', type=str, default='../data/qrels_toy')
    parser.add_argument('-embed', type=str, default='../data/glove.6B.300d.txt')
    parser.add_argument('-vocab_size', type=int, default=400002)
    parser.add_argument('-embed_dim', type=int, default=300)
    parser.add_argument('-res', type=str, default='../results/cknrm.trec')
    parser.add_argument('-res_f', type=str, default='../features/cknrm_features')
    parser.add_argument('-depth', type=int, default=20)
    parser.add_argument('-gamma', type=float, default=0.99)
    parser.add_argument('-T', type=int, default=4)
    parser.add_argument('-n_kernels', type=int, default=21)
    parser.add_argument('-max_query_len', type=int, default=20)
    parser.add_argument('-max_seq_len', type=int, default=128)
    parser.add_argument('-epoch', type=int, default=1)
    parser.add_argument('-batch_size', type=int, default=32)
    args = parser.parse_args()

    # init embedding
    word2vec, embedding_init = embloader(args)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    policy = all_policy(args, embedding_init)
    policy.to(device)
    p_optim = torch.optim.Adam(filter(lambda p: p.requires_grad, policy.parameters()), lr=1e-3)

    # init model
    model = cknrm(args, embedding_init)
    model.to(device)

    # init optimizer and load dev_data
    m_optim = torch.optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=1e-3)
    dev_data = dev_dataloader(args, word2vec)

    # loss function
    crit = nn.MarginRankingLoss(margin=1, reduction='mean')
    crit.to(device)

    if torch.cuda.device_count() > 1:
        policy = nn.DataParallel(policy)
        model = nn.DataParallel(model)
        crit = nn.DataParallel(crit)

    if args.mode == 'train':
        train(args, policy, p_optim, model, m_optim, crit, word2vec, dev_data, device)
    elif args.mode == 'infer':
        assert args.checkpoint is not None
        state_dict=torch.load(args.checkpoint)
        model.load_state_dict(state_dict)
        ndcg, features = dev(args, model, dev_data, device)
        with open(args.res_f, 'w') as writer:
            for feature in features:
                writer.write(feature+'\n')
    else:
        print('mode must be train or infer!')

if __name__ == "__main__":
    main()
