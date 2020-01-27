import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

from model_utils import kernal_mus, kernel_sigmas

class knrm(nn.Module):
    def __init__(self, args, embedding_init=None):
        super(knrm, self).__init__()
        tensor_mu = torch.FloatTensor(kernal_mus(args.n_kernels))
        tensor_sigma = torch.FloatTensor(kernel_sigmas(args.n_kernels))
        if torch.cuda.is_available():
            tensor_mu = tensor_mu.cuda()
            tensor_sigma = tensor_sigma.cuda()
        self.mu = Variable(tensor_mu, requires_grad=False).view(1, 1, 1, args.n_kernels)
        self.sigma = Variable(tensor_sigma, requires_grad=False).view(1, 1, 1, args.n_kernels)

        self.embedding = nn.Embedding(args.vocab_size, args.embed_dim)
        if embedding_init is not None:
            em = torch.tensor(embedding_init, dtype=torch.float32)
            self.embedding.weight = nn.Parameter(em)
            self.embedding.weight.requires_grad = True

        feature_dim = args.n_kernels + 1
        self.dense = nn.Linear(feature_dim, 1)

    def get_intersect_matrix(self, q_embed, d_embed, attn_q, attn_d):
        sim = torch.bmm(q_embed, torch.transpose(d_embed, 1, 2)).view(q_embed.size()[0], q_embed.size()[1], d_embed.size()[1], 1)
        pooling_value = torch.exp((- ((sim - self.mu) ** 2) / (self.sigma ** 2) / 2)) * attn_d.type_as(self.sigma)
        pooling_sum = torch.sum(pooling_value, 2)
        log_pooling_sum = torch.log(torch.clamp(pooling_sum, min=1e-10)) * attn_q.type_as(self.sigma) * 0.01
        log_pooling_sum = torch.sum(log_pooling_sum, 1)
        return log_pooling_sum

    def forward(self, q_embed, d_embed, mask_q, mask_d, score_feature=None):
        q_embed_norm = F.normalize(q_embed, 2, 2)
        d_embed_norm = F.normalize(d_embed, 2, 2)
        mask_d = mask_d.view(mask_d.size()[0], 1, mask_d.size()[1], 1)
        mask_q = mask_q.view(mask_q.size()[0], mask_q.size()[1], 1)

        log_pooling_sum = self.get_intersect_matrix(q_embed_norm, d_embed_norm, mask_q, mask_d)
        if score_feature is not None:
            log_pooling_sum = torch.cat([log_pooling_sum, score_feature.unsqueeze(1)], 1)
        score = torch.squeeze(self.dense(log_pooling_sum), 1)
        return score, log_pooling_sum
