CUDA_VISIBLE_DEVICES=0 \
python main.py \
        -mode train \
        -model bert \
        -train ../data/triples.train.small.tsv \
        -max_input 1280000 \
        -pretrain allenai/scibert_scivocab_uncased \
        -save_best ../checkpoints/reinfoselect_bert.bin \
        -dev ../data/dev_toy.tsv \
        -qrels ../data/qrels_toy \
        -embed ../data/glove.6B.300d.txt \
        -vocab_size 400002 \
        -embed_dim 300 \
        -res_trec ../results/bert.trec \
        -res_json ../results/bert.json \
        -res_feature ../features/bert_features \
        -depth 20 \
        -gamma 0.99 \
        -T 1 \
        -n_kernels 21 \
        -max_query_len 20 \
        -max_seq_len 128 \
        -epoch 1 \
        -batch_size 4
