# -*- coding:utf-8 -*-

import tensorflow as tf
from tensorflow.python.layers.core import Dense
from tensorflow.contrib.seq2seq.python.ops import attention_wrapper

import numpy as np
import os
import data_utils


class attention_seq2seq():
    """
    seq2seq模型
    """

    def __init__(self, vocab_size, mode='train'):
        self.embedding_size = 128
        self.vocab_size = vocab_size
        self.hidden_size = 128
        self.num_layers = 1
        self.learning_rate = 0.01
        self.mode=mode

    def build_model(self):
        self.init_placeholders()
        self.build_encoder()
        self.build_decoder()

        self.summary_op = tf.summary.merge_all()

    def init_placeholders(self):
        self.inputs = tf.placeholder(tf.int32, [None, None], name='inputs')
        self.decoder_input = tf.placeholder(tf.int32, [None, None], name='decorder_inputs')
        self.targets = tf.placeholder(tf.int32, [None, None], name='targets')

        self.batch_size = tf.shape(self.inputs)[0]
        self.source_sequence_length = tf.placeholder(tf.int32, (None,), name='source_sequence_length')
        self.target_sequence_length = tf.placeholder(tf.int32, (None,), name='target_sequence_length')
        self.max_target_sequence_length = tf.reduce_max(self.target_sequence_length, name='max_target_len')

    def build_encoder(self):
        """
        encoder
        :return:
        """
        print('build encoder...')
        encoder_embed_input = tf.contrib.layers.embed_sequence(ids=self.inputs, vocab_size=self.vocab_size,
                                                               embed_dim=self.embedding_size)

        def lstm_cell():
            lstm_cell = tf.contrib.rnn.LSTMCell(self.hidden_size,
                                                initializer=tf.random_uniform_initializer(-0.1, 0.1, seed=2))
            return lstm_cell

        cells = tf.contrib.rnn.MultiRNNCell([lstm_cell() for _ in range(self.num_layers)])
        self.encoder_outputs, self.encoder_states = tf.nn.dynamic_rnn(cell=cells,
                                                                      inputs=encoder_embed_input,
                                                                      sequence_length=self.source_sequence_length,
                                                                      dtype=tf.float32)

    def build_decoder(self):
        """
        decoder
        :return:
        """
        print('build decoder with attention...')
        decoder_embeddings = tf.Variable(tf.random_uniform([self.vocab_size, self.embedding_size]))
        decoder_embed_input = tf.nn.embedding_lookup(decoder_embeddings, self.decoder_input)

        # 2.1 add attention
        def build_decoder_cell():
            decoder_cell = tf.contrib.rnn.LSTMCell(self.hidden_size,
                                                   initializer=tf.random_uniform_initializer(-0.1, 0.1, seed=2))
            return decoder_cell

        attention_states = self.encoder_outputs
        attention_mechanism = tf.contrib.seq2seq.LuongAttention(
            num_units=self.hidden_size,
            memory=attention_states,
            memory_sequence_length=self.source_sequence_length)

        decoder_cells_list = [build_decoder_cell() for _ in range(self.num_layers)]
        decoder_cells_list[-1] = attention_wrapper.AttentionWrapper(
            cell=decoder_cells_list[-1],
            attention_mechanism=attention_mechanism,
            attention_layer_size=self.hidden_size
        )

        decoder_cells = tf.contrib.rnn.MultiRNNCell(decoder_cells_list)

        initial_state = [state for state in self.encoder_states]
        initial_state[-1] = decoder_cells_list[-1].zero_state(
            batch_size=self.batch_size, dtype=tf.float32)
        decoder_initial_state = tuple(initial_state)

        # 全连接
        output_layer = Dense(self.vocab_size,
                             kernel_initializer=tf.truncated_normal_initializer(mean=0.0, stddev=0.1))

        # 4. Training decoder
        if self.mode == 'train':
            with tf.variable_scope("decode"):
                training_helper = tf.contrib.seq2seq.TrainingHelper(inputs=decoder_embed_input,
                                                                    sequence_length=self.target_sequence_length,
                                                                    time_major=False)
                training_decoder = tf.contrib.seq2seq.BasicDecoder(cell=decoder_cells,
                                                                   helper=training_helper,
                                                                   initial_state=decoder_initial_state,
                                                                   output_layer=output_layer)
                self.training_decoder_output, _, _ = tf.contrib.seq2seq.dynamic_decode(training_decoder,
                                                                                       impute_finished=True,
                                                                                       maximum_iterations=self.max_target_sequence_length)
            self.optimization()
        else:
            with tf.variable_scope("decode", reuse=True):
                start_tokens = tf.tile(tf.constant([data_utils.start_token], dtype=tf.int32), [self.batch_size],
                                       name='start_tokens')
                end_tokens = data_utils.end_token
                # use greedy in predict phrase
                predicting_helper = tf.contrib.seq2seq.GreedyEmbeddingHelper(embedding=decoder_embeddings,
                                                                             start_tokens=start_tokens,
                                                                             end_token=end_tokens)
                predicting_decoder = tf.contrib.seq2seq.BasicDecoder(cell=decoder_cells,
                                                                     helper=predicting_helper,
                                                                     initial_state=decoder_initial_state,
                                                                     output_layer=output_layer)
                self.predicting_decoder_output, _, _ = tf.contrib.seq2seq.dynamic_decode(predicting_decoder,
                                                                                         impute_finished=True,
                                                                                         maximum_iterations=self.max_target_sequence_length)
                self.predicting_logits = tf.identity(self.predicting_decoder_output.sample_id, name='predictions')

    def optimization(self):
        training_logits = tf.identity(self.training_decoder_output.rnn_output, name='logits')
        masks = tf.sequence_mask(lengths=self.target_sequence_length,
                                 maxlen=self.max_target_sequence_length, dtype=tf.float32, name='masks')
        with tf.name_scope("optimization"):
            self.loss = tf.contrib.seq2seq.sequence_loss(logits=training_logits, targets=self.targets, weights=masks)
            tf.summary.scalar('loss', self.loss)

            self.optimizer = tf.train.AdamOptimizer(learning_rate=self.learning_rate)
            gradients = self.optimizer.compute_gradients(self.loss)
            capped_gradients = [(tf.clip_by_value(grad, -5., 5.), var) for grad, var in gradients if grad is not None]
            self.train_op = self.optimizer.apply_gradients(capped_gradients)

    def train(self, sess, encoder_inputs, encoder_inputs_length,
              decoder_targets, decoder_inputs_length):
        decoder_inputs = np.delete(decoder_targets, -1, axis=1)
        decoder_inputs = np.c_[np.zeros(len(decoder_inputs), dtype=np.int16), decoder_inputs]
        outputs = sess.run([self.train_op, self.loss], feed_dict={self.inputs: encoder_inputs,
                                                                    self.decoder_input: decoder_inputs,
                                                                    self.targets: decoder_targets,
                                                                    self.source_sequence_length: encoder_inputs_length,
                                                                    self.target_sequence_length: decoder_inputs_length})
        return outputs[0], outputs[1]


def train():
    checkpoint = "../model/checkpoint/model.ckpt"

    data_utils.prepare()
    epochs = 100
    with tf.Session() as sess:
        model = attention_seq2seq(data_utils.vocab_size)
        model.build_model()
        sess.run(tf.global_variables_initializer())

        for epoch in range(1, epochs + 1):
            train_set = data_utils.train_set()
            for source_seq, target_seq in train_set:
                encoder_inputs, encoder_inputs_length, decoder_inputs, decoder_inputs_length = data_utils.prepare_train_batch(source_seq, target_seq)
                _, loss = model.train(sess=sess,
                            encoder_inputs=encoder_inputs,
                            encoder_inputs_length=encoder_inputs_length,
                            decoder_targets=decoder_inputs,
                            decoder_inputs_length=decoder_inputs_length)
                print("epoch={}, loss={}".format(epoch, loss))

        saver = tf.train.Saver()
        saver.save(sess, checkpoint)
        print('Model Trained and Saved')

def predit():
    input_sentence = "天王盖地虎"
    data_utils.prepare()
    form_input = []
    for ch in input_sentence:
        form_input.append(data_utils.char_to_index[ch])
    inputs, encoder_inputs_length = data_utils.prepare_predict_batch([form_input])
    checkpoint = "../model/checkpoint/model.ckpt"

    loaded_graph = tf.Graph()
    with tf.Session(graph=loaded_graph) as sess:
        loader = tf.train.import_meta_graph(checkpoint + '.meta')
        loader.restore(sess, checkpoint)

        input_data = loaded_graph.get_tensor_by_name('inputs:0')
        logits = loaded_graph.get_tensor_by_name('predictions:0')
        source_sequence_length = loaded_graph.get_tensor_by_name('source_sequence_length:0')
        target_sequence_length = loaded_graph.get_tensor_by_name('target_sequence_length:0')

        answer_logits = sess.run(logits, feed_dict={input_data: inputs,
                                          target_sequence_length: source_sequence_length,
                                          source_sequence_length: encoder_inputs_length})[0]


if __name__ == '__main__':
    train()
