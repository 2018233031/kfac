# Copyright 2019 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for kfac.fisher_blocks."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# Dependency imports
import numpy as np
import tensorflow as tf

from kfac.python.ops import fisher_blocks as fb
from kfac.python.ops import fisher_factors as ff
from kfac.python.ops import layer_collection as lc
from kfac.python.ops import linear_operator as lo
from kfac.python.ops import utils

# We need to set these constants since the numerical values used in the tests
# were chosen when these used to be the defaults.
ff.set_global_constants(init_covariances_at_zero=False,
                        zero_debias=False,
                        init_inverses_at_zero=False)


def _make_psd(dim):
  """Constructs a PSD matrix of the given dimension."""
  mat = np.ones((dim, dim), dtype=np.float32)
  mat[np.arange(dim), np.arange(dim)] = 2. + np.arange(dim)
  return tf.constant(mat)


class UtilsTest(tf.test.TestCase):

  def testComputePiTracenorm(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      diag = tf.convert_to_tensor([1., 2., 0., 1.])
      left_factor = lo.LinearOperatorDiag(diag)
      right_factor = lo.LinearOperatorFullMatrix(tf.ones([2, 2]))

      # pi is the sqrt of the left trace norm divided by the right trace norm
      pi = fb.compute_pi_tracenorm(left_factor, right_factor)

      pi_val = sess.run(pi)
      self.assertEqual(1., pi_val)


class NaiveFullFBTest(tf.test.TestCase):

  def testNaiveFullFBInitSingleTensor(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveFullFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)

      self.assertAllEqual(params, block.tensors_to_compute_grads())

  def testNaiveFullFBInitTensorTuple(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveFullFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)

      self.assertAllEqual(params, block.tensors_to_compute_grads())

  def testInstantiateFactors(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveFullFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)

      grads = (params[0]**2, tf.sqrt(params[1]))
      block.instantiate_factors(grads, 0.5)

  def testMultiplyInverseTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveFullFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)
      grads = (params[0]**2, tf.sqrt(params[1]))
      block.instantiate_factors((grads,), 0.5)
      block._factor.instantiate_cov_variables()
      block.register_inverse()
      block._factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._factor.make_inverse_update_ops())

      vector = tf.ones(3,) * 2
      output = block.multiply_inverse(vector)

      self.assertAllClose(sess.run(vector * 2 / 3.), sess.run(output))

  def testMultiplyInverseNotTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = tf.constant([[1.], [2.]])
      block = fb.NaiveFullFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)
      grads = params**2
      block.instantiate_factors((grads,), 0.5)
      block._factor.instantiate_cov_variables()
      block.register_inverse()
      block._factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._factor.make_inverse_update_ops())

      vector = tf.ones(2,) * 2
      output = block.multiply_inverse(vector)

      self.assertAllClose(sess.run(vector * 2 / 3.), sess.run(output))

  def testMultiplyInverseAgainstExplicit(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveFullFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)
      grads = (tf.constant([2., 3.]), tf.constant(4.))
      damping = 0.5
      block.instantiate_factors((grads,), damping)
      block._factor.instantiate_cov_variables()
      block.register_inverse()
      block._factor.instantiate_inv_variables()

      sess.run(tf.global_variables_initializer())

      # Make sure our inverse is something other than the identity.
      sess.run(block._factor._cov.add_to_average(_make_psd(3)))

      sess.run(block._factor.make_inverse_update_ops())

      v_flat = np.array([4., 5., 6.], dtype=np.float32)
      vector = utils.column_to_tensors(params, tf.constant(v_flat))
      output = block.multiply_inverse(vector)
      output_flat = sess.run(utils.tensors_to_column(output)).ravel()

      full = sess.run(block.full_fisher_block())
      explicit = np.dot(np.linalg.inv(full + damping * np.eye(3)), v_flat)

      self.assertAllClose(output_flat, explicit)


class NaiveDiagonalFBTest(tf.test.TestCase):

  def testNaiveDiagonalFBInitSingleTensor(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveDiagonalFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)

      self.assertAllEqual(params, block.tensors_to_compute_grads())

  def testNaiveDiagonalFBInitTensorTuple(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveDiagonalFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)

      self.assertAllEqual(params, block.tensors_to_compute_grads())

  def testInstantiateFactors(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveDiagonalFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)

      grads = (params[0]**2, tf.sqrt(params[1]))
      block.instantiate_factors(grads, 0.5)

  def testMultiplyInverseTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveDiagonalFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)
      grads = (params[0]**2, tf.sqrt(params[1]))
      block.instantiate_factors((grads,), 0.5)
      block._factor.instantiate_cov_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._factor.make_inverse_update_ops())

      vector = tf.ones(3,) * 2
      output = block.multiply_inverse(vector)

      self.assertAllClose(sess.run(vector * 2 / 3.), sess.run(output))

  def testMultiplyInverseNotTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = tf.constant([[1.], [2.]])
      block = fb.NaiveDiagonalFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)
      grads = params**2
      block.instantiate_factors((grads,), 0.5)
      block._factor.instantiate_cov_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._factor.make_inverse_update_ops())
      vector = tf.ones(2,) * 2
      output = block.multiply_inverse(vector)

      self.assertAllClose(sess.run(vector * 2 / 3.), sess.run(output))

  def testMultiplyInverseAgainstExplicit(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = (tf.constant([1., 2.]), tf.constant(3.))
      block = fb.NaiveDiagonalFB(lc.LayerCollection(), params)
      block.register_additional_tower(32)
      grads = (params[0]**2, tf.sqrt(params[1]))
      damping = 0.5
      block.instantiate_factors((grads,), damping)
      block._factor.instantiate_cov_variables()

      cov = tf.reshape(tf.constant([2., 3., 4.]), [-1, 1])

      sess.run(tf.global_variables_initializer())
      sess.run(block._factor._cov.add_to_average(cov))

      sess.run(block._factor.make_inverse_update_ops())

      v_flat = np.array([4., 5., 6.], dtype=np.float32)
      vector = utils.column_to_tensors(params, tf.constant(v_flat))
      output = block.multiply_inverse(vector)
      output_flat = sess.run(utils.tensors_to_column(output)).ravel()

      full = sess.run(block.full_fisher_block())
      explicit = np.dot(np.linalg.inv(full + damping * np.eye(3)), v_flat)

      self.assertAllClose(output_flat, explicit)


class FullyConnectedDiagonalFBTest(tf.test.TestCase):

  def setUp(self):
    super(FullyConnectedDiagonalFBTest, self).setUp()

    self.batch_size = 4
    self.input_size = 6
    self.output_size = 3

    self.inputs = np.random.randn(self.batch_size, self.input_size).astype(
        np.float32)
    self.outputs = np.zeros([self.batch_size, self.output_size]).astype(
        np.float32)
    self.output_grads = np.random.randn(self.batch_size,
                                        self.output_size).astype(np.float32)
    self.w = np.random.randn(self.input_size, self.output_size).astype(
        np.float32)
    self.b = np.random.randn(self.output_size).astype(np.float32)

  def fisherApprox(self, has_bias=False):
    """Fisher approximation using default inputs."""
    if has_bias:
      inputs = np.concatenate(
          [self.inputs, np.ones([self.batch_size, 1])], axis=1)
    else:
      inputs = self.inputs
    return self.buildDiagonalFisherApproximation(inputs, self.output_grads)

  def buildDiagonalFisherApproximation(self, inputs, output_grads):
    """Builds explicit diagonal Fisher approximation.

    Fisher's diagonal is (d loss / d w)'s elements squared for
      d/dw = E[outer(input, output_grad)]

    where the expectation is taken over examples.

    Args:
      inputs: np.array of shape [batch_size, input_size].
      output_grads: np.array of shape [batch_size, output_size].

    Returns:
      Diagonal np.array of shape [num_params, num_params] for num_params =
      input_size * output_size.
    """
    batch_size = inputs.shape[0]
    assert output_grads.shape[0] == batch_size
    input_size = inputs.shape[1]
    output_size = output_grads.shape[1]
    fisher_diag = np.zeros((input_size, output_size))
    for i in range(batch_size):
      fisher_diag += np.square(np.outer(inputs[i], output_grads[i]))
    return np.diag(fisher_diag.flatten()) / batch_size

  def testMultiply(self):
    result, _ = self.runFisherBlockOps(self.w, [self.inputs], [self.outputs],
                                       [self.output_grads])

    # Construct Fisher-vector product.
    expected_result = self.fisherApprox().dot(self.w.flatten())
    expected_result = expected_result.reshape(
        [self.input_size, self.output_size])

    self.assertAllClose(expected_result, result)

  def testMultiplyInverse(self):
    _, result = self.runFisherBlockOps(self.w, [self.inputs], [self.outputs],
                                       [self.output_grads])

    # Construct inverse Fisher-vector product.
    expected_result = np.linalg.inv(self.fisherApprox()).dot(self.w.flatten())
    expected_result = expected_result.reshape(
        [self.input_size, self.output_size])

    self.assertAllClose(expected_result, result)

  def testRegisterAdditionalTower(self):
    """Ensure 1 big tower and 2 small towers are equivalent."""
    multiply_result_big, multiply_inverse_result_big = self.runFisherBlockOps(
        self.w, [self.inputs], [self.outputs], [self.output_grads])
    multiply_result_small, multiply_inverse_result_small = (
        self.runFisherBlockOps(self.w, np.split(self.inputs, 2),
                               np.split(self.outputs, 2),
                               np.split(self.output_grads, 2)))

    self.assertAllClose(multiply_result_big, multiply_result_small)
    self.assertAllClose(multiply_inverse_result_big,
                        multiply_inverse_result_small)

  def testMultiplyHasBias(self):
    result, _ = self.runFisherBlockOps((self.w, self.b), [self.inputs],
                                       [self.outputs], [self.output_grads])
    expected_result = self.fisherApprox(True).dot(
        np.concatenate([self.w.flatten(), self.b.flatten()]))
    expected_result = expected_result.reshape(
        [self.input_size + 1, self.output_size])
    expected_result = (expected_result[:-1], expected_result[-1])

    self.assertEqual(len(result), 2)
    self.assertAllClose(expected_result[0], result[0])
    self.assertAllClose(expected_result[1], result[1])

  def runFisherBlockOps(self, params, inputs, outputs, output_grads):
    """Run Ops guaranteed by FisherBlock interface.

    Args:
      params: Tensor or 2-tuple of Tensors. Represents weights or weights and
        bias of this layer.
      inputs: list of Tensors of shape [batch_size, input_size]. Inputs to
        layer.
      outputs: list of Tensors of shape [batch_size, output_size].
        Preactivations produced by layer.
      output_grads: list of Tensors of shape [batch_size, output_size].
        Gradient of loss with respect to 'outputs'.

    Returns:
      multiply_result: Result of FisherBlock.multiply(params)
      multiply_inverse_result: Result of FisherBlock.multiply_inverse(params)
    """
    with tf.Graph().as_default(), self.test_session() as sess:
      inputs = as_tensors(inputs)
      outputs = as_tensors(outputs)
      output_grads = as_tensors(output_grads)
      params = as_tensors(params)

      block = fb.FullyConnectedDiagonalFB(
          lc.LayerCollection(), has_bias=isinstance(params, (tuple, list)))
      for (i, o) in zip(inputs, outputs):
        block.register_additional_tower(i, o)

      block.instantiate_factors((output_grads,), damping=0.0)
      block._factor.instantiate_cov_variables()

      sess.run(tf.global_variables_initializer())
      sess.run(block._factor.make_covariance_update_op(0.0, 1.0))
      multiply_result = sess.run(block.multiply(params))
      multiply_inverse_result = sess.run(block.multiply_inverse(params))

    return multiply_result, multiply_inverse_result


class FullyConnectedKFACBasicFBSparseInputTest(tf.test.TestCase):

  def testFullyConnectedKFACBasicFBInit(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([1., 2.])
      outputs = tf.constant([3., 4.])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection())
      block.register_additional_tower(inputs, outputs)

      self.assertAllEqual([outputs], block.tensors_to_compute_grads())

  def testInstantiateFactors(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)

      # Create a Fisher Block.
      vocab_size = 5
      block = fb.FullyConnectedKFACBasicFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True)

      # Add some examples.
      inputs = tf.constant([[0, 1], [1, 2], [2, 3]])
      inputs.one_hot_depth = vocab_size
      outputs = tf.constant([[0.], [1.], [2.]])
      block.register_additional_tower(inputs, outputs)

      # Instantiate factor's variables. Ensure it doesn't fail.
      grads = outputs**2.
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)

  def testMultiplyInverse(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)

      # Create a Fisher Block.
      vocab_size = 5
      block = fb.FullyConnectedKFACBasicFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True)

      # Add some examples.
      inputs = tf.constant([[0, 1], [1, 2], [2, 3]])
      inputs.one_hot_depth = vocab_size
      outputs = tf.constant([[0.], [1.], [2.]])
      block.register_additional_tower(inputs, outputs)

      # Instantiate factor's variables. Ensure it doesn't fail.
      grads = outputs**2.
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Create a sparse update.
      indices = tf.constant([1, 3, 4])
      values = tf.constant([[1.], [1.], [1.]])
      sparse_vector = tf.IndexedSlices(
          values, indices, dense_shape=[vocab_size, 1])
      dense_vector = tf.reshape([0., 1., 0., 1., 1.], [vocab_size, 1])

      # Compare Fisher-vector product against explicit result.
      result = block.multiply_inverse(sparse_vector)
      expected_result = tf.matrix_solve(block.full_fisher_block(), dense_vector)

      sess.run(tf.global_variables_initializer())
      self.assertAlmostEqual(
          sess.run(expected_result[1]), sess.run(result.values[0]))
      self.assertAlmostEqual(
          sess.run(expected_result[3]), sess.run(result.values[1]))
      self.assertAlmostEqual(
          sess.run(expected_result[4]), sess.run(result.values[2]))


class FullyConnectedKFACBasicFBTest(tf.test.TestCase):

  def testFullyConnectedKFACBasicFBInit(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([1., 2.])
      outputs = tf.constant([3., 4.])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection())
      block.register_additional_tower(inputs, outputs)

      self.assertAllEqual([outputs], block.tensors_to_compute_grads())

  def testInstantiateFactorsHasBias(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([[1., 2.], [3., 4.]])
      outputs = tf.constant([[3., 4.], [5., 6.]])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection(), has_bias=True)
      block.register_additional_tower(inputs, outputs)

      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)

  def testInstantiateFactorsNoBias(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([[1., 2.], [3., 4.]])
      outputs = tf.constant([[3., 4.], [5., 6.]])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection(), has_bias=False)
      block.register_additional_tower(inputs, outputs)

      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)

  def testMultiplyInverseTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      inputs = tf.constant([[1., 2., 3.], [3., 4., 5.], [5., 6., 7.]])
      outputs = tf.constant([[3., 4.], [5., 6.]])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection(), has_bias=False)
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)

      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      vector = (
          np.arange(2, 6).reshape(2, 2).astype(np.float32),  #
          np.arange(1, 3).reshape(2, 1).astype(np.float32))
      output = block.multiply_inverse((tf.constant(vector[0]),
                                       tf.constant(vector[1])))

      output = sess.run(output)
      self.assertAllClose([[0.686291, 1.029437], [1.372583, 1.715729]],
                          output[0])
      self.assertAllClose([0.343146, 0.686291], output[1])

  def testMultiplyInverseNotTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      inputs = tf.constant([[1., 2.], [3., 4.]])
      outputs = tf.constant([[3., 4.], [5., 6.]])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection(), has_bias=False)
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      vector = np.arange(2, 6).reshape(2, 2).astype(np.float32)
      output = block.multiply_inverse(tf.constant(vector))

      self.assertAllClose([[0.686291, 1.029437], [1.372583, 1.715729]],
                          sess.run(output))

  def testMultiplyInverseAgainstExplicit(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      input_dim, output_dim = 3, 2
      inputs = tf.zeros([32, input_dim])
      outputs = tf.zeros([32, output_dim])
      params = tf.zeros([input_dim, output_dim])
      block = fb.FullyConnectedKFACBasicFB(lc.LayerCollection(), has_bias=False)
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      damping = 0.  # This test is only valid without damping.
      block.instantiate_factors(((grads,),), damping)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()

      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor._cov.add_to_average(_make_psd(3)))
      sess.run(block._output_factor._cov.add_to_average(_make_psd(2)))

      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      v_flat = np.arange(6, dtype=np.float32)
      vector = utils.column_to_tensors(params, tf.constant(v_flat))
      output = block.multiply_inverse(vector)
      output_flat = sess.run(utils.tensors_to_column(output)).ravel()

      full = sess.run(block.full_fisher_block())
      explicit = np.dot(np.linalg.inv(full + damping * np.eye(6)), v_flat)

      self.assertAllClose(output_flat, explicit)


class ConvDiagonalFBTest(tf.test.TestCase):

  def setUp(self):
    super(ConvDiagonalFBTest, self).setUp()

    self.batch_size = 2
    self.height = 8
    self.width = 4
    self.input_channels = 6
    self.output_channels = 3
    self.kernel_size = 1

    self.inputs = np.random.randn(self.batch_size, self.height, self.width,
                                  self.input_channels).astype(np.float32)
    self.outputs = np.zeros(
        [self.batch_size, self.height, self.width,
         self.output_channels]).astype(np.float32)
    self.output_grads = np.random.randn(
        self.batch_size, self.height, self.width, self.output_channels).astype(
            np.float32)
    self.w = np.random.randn(self.kernel_size, self.kernel_size,
                             self.input_channels, self.output_channels).astype(
                                 np.float32)
    self.b = np.random.randn(self.output_channels).astype(np.float32)

  def fisherApprox(self, has_bias=False):
    """Fisher approximation using default inputs."""
    if has_bias:
      inputs = np.concatenate(
          [self.inputs,
           np.ones([self.batch_size, self.height, self.width, 1])],
          axis=-1)
    else:
      inputs = self.inputs
    return self.buildDiagonalFisherApproximation(inputs, self.output_grads,
                                                 self.kernel_size)

  def buildDiagonalFisherApproximation(self, inputs, output_grads, kernel_size):
    r"""Builds explicit diagonal Fisher approximation.

    Fisher's diagonal is (d loss / d w)'s elements squared for
      d/dw = E[\sum_{loc} outer(input_{loc}, output_grad_{loc})]

    where the expectation is taken over examples and the sum over (x, y)
    locations upon which the convolution is applied.

    Args:
      inputs: np.array of shape [batch_size, height, width, input_channels].
      output_grads: np.array of shape [batch_size, height, width,
        output_channels].
      kernel_size: int. height and width of kernel.

    Returns:
      Diagonal np.array of shape [num_params, num_params] for num_params =
      kernel_size^2 * input_channels * output_channels.
    """
    batch_size, height, width, input_channels = inputs.shape
    assert output_grads.shape[0] == batch_size
    assert output_grads.shape[1] == height
    assert output_grads.shape[2] == width
    output_channels = output_grads.shape[3]

    # If kernel_size == 1, then we don't need to worry about capturing context
    # around the pixel upon which a convolution is applied. This makes testing
    # easier.
    assert kernel_size == 1, "kernel_size != 1 isn't supported."
    num_locations = height * width
    inputs = np.reshape(inputs, [batch_size, num_locations, input_channels])
    output_grads = np.reshape(output_grads,
                              [batch_size, num_locations, output_channels])

    fisher_diag = np.zeros((input_channels, output_channels))
    for i in range(batch_size):
      # Each example's approximation is a square(sum-of-outer-products).
      example_fisher_diag = np.zeros((input_channels, output_channels))
      for j in range(num_locations):
        example_fisher_diag += np.outer(inputs[i, j], output_grads[i, j])
      fisher_diag += np.square(example_fisher_diag)

    # Normalize by batch_size (not num_locations).
    return np.diag(fisher_diag.flatten()) / batch_size

  def testMultiply(self):
    result, _ = self.runFisherBlockOps(self.w, [self.inputs], [self.outputs],
                                       [self.output_grads])

    # Construct Fisher-vector product.
    expected_result = self.fisherApprox().dot(self.w.flatten())
    expected_result = expected_result.reshape([
        self.kernel_size, self.kernel_size, self.input_channels,
        self.output_channels
    ])

    self.assertAllClose(expected_result, result)

  def testMultiplyInverse(self):
    _, result = self.runFisherBlockOps(self.w, [self.inputs], [self.outputs],
                                       [self.output_grads])

    # Construct inverse Fisher-vector product.
    expected_result = np.linalg.inv(self.fisherApprox()).dot(self.w.flatten())
    expected_result = expected_result.reshape([
        self.kernel_size, self.kernel_size, self.input_channels,
        self.output_channels
    ])

    self.assertAllClose(expected_result, result, atol=1e-3)

  def testRegisterAdditionalTower(self):
    """Ensure 1 big tower and 2 small towers are equivalent."""
    multiply_result_big, multiply_inverse_result_big = self.runFisherBlockOps(
        self.w, [self.inputs], [self.outputs], [self.output_grads])
    multiply_result_small, multiply_inverse_result_small = (
        self.runFisherBlockOps(self.w, np.split(self.inputs, 2),
                               np.split(self.outputs, 2),
                               np.split(self.output_grads, 2)))

    self.assertAllClose(multiply_result_big, multiply_result_small)
    self.assertAllClose(multiply_inverse_result_big,
                        multiply_inverse_result_small)

  def testMultiplyHasBias(self):
    result, _ = self.runFisherBlockOps((self.w, self.b), [self.inputs],
                                       [self.outputs], [self.output_grads])
    # Clone 'b' along 'input_channels' dimension.
    b_filter = np.tile(
        np.reshape(self.b, [1, 1, 1, self.output_channels]),
        [self.kernel_size, self.kernel_size, 1, 1])
    params = np.concatenate([self.w, b_filter], axis=2)
    expected_result = self.fisherApprox(True).dot(params.flatten())

    # Extract 'b' from concatenated parameters.
    expected_result = expected_result.reshape([
        self.kernel_size, self.kernel_size, self.input_channels + 1,
        self.output_channels
    ])
    expected_result = (expected_result[:, :, 0:-1, :],
                       np.reshape(expected_result[:, :, -1, :],
                                  [self.output_channels]))

    self.assertEqual(len(result), 2)
    self.assertAllClose(expected_result[0], result[0])
    self.assertAllClose(expected_result[1], result[1])

  def runFisherBlockOps(self, params, inputs, outputs, output_grads):
    """Run Ops guaranteed by FisherBlock interface.

    Args:
      params: Tensor or 2-tuple of Tensors. Represents weights or weights and
        bias of this layer.
      inputs: list of Tensors of shape [batch_size, input_size]. Inputs to
        layer.
      outputs: list of Tensors of shape [batch_size, output_size].
        Preactivations produced by layer.
      output_grads: list of Tensors of shape [batch_size, output_size].
        Gradient of loss with respect to 'outputs'.

    Returns:
      multiply_result: Result of FisherBlock.multiply(params)
      multiply_inverse_result: Result of FisherBlock.multiply_inverse(params)
    """
    with tf.Graph().as_default(), self.test_session() as sess:
      inputs = as_tensors(inputs)
      outputs = as_tensors(outputs)
      output_grads = as_tensors(output_grads)
      params = as_tensors(params)

      block = fb.ConvDiagonalFB(
          lc.LayerCollection(), params, strides=[1, 1, 1, 1], padding='SAME')
      for (i, o) in zip(inputs, outputs):
        block.register_additional_tower(i, o)

      block.instantiate_factors((output_grads,), damping=0.0)
      block._factor.instantiate_cov_variables()

      sess.run(tf.global_variables_initializer())
      sess.run(block._factor.make_covariance_update_op(0.0, 1.0))
      multiply_result = sess.run(block.multiply(params))
      multiply_inverse_result = sess.run(block.multiply_inverse(params))

    return multiply_result, multiply_inverse_result


class DepthwiseConvKFCBasicFBTest(tf.test.TestCase):

  def testInstantiateFactors(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      params = tf.random_normal((3, 3, 8, 2))
      inputs = tf.random_normal((32, 5, 5, 8))
      outputs = tf.random_normal((32, 5, 5, 16))
      layer_collection = lc.LayerCollection()
      block = fb.DepthwiseConvKFCBasicFB(
          layer_collection, params=params, strides=[1, 1, 1, 1], padding='SAME')
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)

  def testMultiplyInverse(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = tf.random_normal((3, 3, 8, 2))
      inputs = tf.random_normal((32, 5, 5, 8))
      outputs = tf.random_normal((32, 5, 5, 16))
      layer_collection = lc.LayerCollection()
      block = fb.DepthwiseConvKFCBasicFB(
          layer_collection, params=params, strides=[1, 1, 1, 1], padding='SAME')
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Ensure inverse update op doesn't crash.
      sess.run(tf.global_variables_initializer())
      sess.run([
          factor.make_inverse_update_ops()
          for factor in layer_collection.get_factors()
      ])

      # Ensure inverse-vector multiply doesn't crash.
      output = block.multiply_inverse(params)
      sess.run(output)

      # Ensure same shape.
      self.assertAllEqual(output.shape, params.shape)


class ConvKFCBasicFBTest(tf.test.TestCase):

  def _testConvKFCBasicFBInitParams(self, params):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      if isinstance(params, (list, tuple)):
        params = [tf.constant(param) for param in params]
      else:
        params = tf.constant(params)
      inputs = tf.random_normal((2, 2, 2))
      outputs = tf.random_normal((2, 2, 2))
      block = fb.ConvKFCBasicFB(
          lc.LayerCollection(), params=params, padding='SAME')
      block.register_additional_tower(inputs, outputs)

      self.assertAllEqual([outputs], block.tensors_to_compute_grads())

  def testConvKFCBasicFBInitParamsParamsTuple(self):
    self._testConvKFCBasicFBInitParams([np.ones([1, 2, 2]), np.ones([2])])

  def testConvKFCBasicFBInitParamsParamsSingle(self):
    self._testConvKFCBasicFBInitParams([np.ones([1, 2, 2])])

  def testMultiplyInverseTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = tf.random_normal((2, 2, 2, 2))
      inputs = tf.random_normal((2, 2, 2, 2))
      outputs = tf.random_normal((2, 2, 2, 2))
      block = fb.ConvKFCBasicFB(
          lc.LayerCollection(), params=params, padding='SAME')
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      vector = (np.arange(1, 15).reshape(7, 2).astype(np.float32),
                np.arange(2, 4).reshape(2, 1).astype(np.float32))
      output = block.multiply_inverse((tf.constant(vector[0]),
                                       tf.constant(vector[1])))

      output = sess.run(output)
      self.assertAllClose([0.136455, 0.27291], output[0][0])
      self.assertAllClose([0.27291, 0.409365], output[1])

  def testMultiplyInverseNotTuple(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = tf.random_normal((2, 2, 2, 2))
      inputs = tf.random_normal((2, 2, 2, 2))
      outputs = tf.random_normal((2, 2, 2, 2))
      block = fb.ConvKFCBasicFB(
          lc.LayerCollection(), params=params, padding='SAME')
      block.register_additional_tower(inputs, outputs)
      self.assertFalse(block._has_bias)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      vector = np.arange(1, 17).reshape(8, 2).astype(np.float32)
      output = block.multiply_inverse(tf.constant(vector))

      self.assertAllClose([0.136455, 0.27291], sess.run(output)[0])

  def testMultiplyInverseNotTupleWithBias(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = [tf.random_normal((2, 2, 2, 2))]
      inputs = tf.random_normal((2, 2, 2, 2))
      outputs = tf.random_normal((2, 2, 2, 2))
      block = fb.ConvKFCBasicFB(
          lc.LayerCollection(), params=params, padding='SAME')
      block.register_additional_tower(inputs, outputs)
      self.assertTrue(block._has_bias)
      grads = outputs**2
      block.instantiate_factors(((grads,),), 0.5)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Make sure our inverse is something other than the identity.
      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      vector = np.arange(1, 19).reshape(9, 2).astype(np.float32)
      output = block.multiply_inverse(tf.constant(vector))

      self.assertAllClose([0.136455, 0.27291], sess.run(output)[0])

  def testMultiplyInverseAgainstExplicit(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)
      params = tf.zeros((2, 2, 2, 2))
      inputs = tf.zeros((2, 2, 2, 2))
      outputs = tf.zeros((2, 2, 2, 2))
      block = fb.ConvKFCBasicFB(
          lc.LayerCollection(), params=params, padding='SAME')
      block.register_additional_tower(inputs, outputs)
      grads = outputs**2
      damping = 0.  # This test is only valid without damping.
      block.instantiate_factors(((grads,),), damping)
      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      sess.run(tf.global_variables_initializer())
      sess.run(block._input_factor._cov.add_to_average(_make_psd(8)))
      sess.run(block._output_factor._cov.add_to_average(_make_psd(2)))

      sess.run(block._input_factor.make_inverse_update_ops())
      sess.run(block._output_factor.make_inverse_update_ops())

      v_flat = np.arange(16, dtype=np.float32)
      vector = utils.column_to_tensors(params, tf.constant(v_flat))
      output = block.multiply_inverse(vector)
      output_flat = sess.run(utils.tensors_to_column(output)).ravel()

      full = sess.run(block.full_fisher_block())
      explicit = np.dot(np.linalg.inv(full + damping * np.eye(16)), v_flat)

      self.assertAllClose(output_flat, explicit)


class FullyConnectedSeriesFBTest(tf.test.TestCase):

  def testFullyConnectedSeriesFBInit(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([1., 2.])
      outputs = tf.constant([3., 4.])
      block = fb.FullyConnectedSeriesFB(lc.LayerCollection())
      block.register_additional_tower([inputs], [outputs])
      self.assertAllEqual([[outputs]], block.tensors_to_compute_grads())

  def testInstantiateFactorsHasBias(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([[1., 2.], [3., 4.]])
      outputs = tf.constant([[3., 4.], [5., 6.]])
      block = fb.FullyConnectedSeriesFB(
          lc.LayerCollection(),
          has_bias=True)
      block.register_additional_tower([inputs], [outputs])
      grads = outputs**2
      block.instantiate_factors((((grads,),),), 0.5)

  def testInstantiateFactorsNoBias(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)
      inputs = tf.constant([[1., 2.], [3., 4.]])
      outputs = tf.constant([[3., 4.], [5., 6.]])
      block = fb.FullyConnectedSeriesFB(
          lc.LayerCollection(),
          has_bias=False)
      block.register_additional_tower([inputs], [outputs])
      grads = outputs**2
      block.instantiate_factors((((grads,),),), 0.5)


class FullyConnectedMultiIndepFBSparseInputTest(tf.test.TestCase):

  def testInstantiateFactors(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)

      vocab_size = 5
      block = fb.FullyConnectedMultiIndepFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True)

      inputs = [tf.constant([[0, 1], [1, 2], [2, 3]]),
                tf.constant([[0, 0], [0, 0], [0, 4]])]
      for input in inputs:
        input.one_hot_depth = vocab_size
      outputs = [tf.constant([[0.], [1.], [2.]]),
                 tf.constant([[0.1], [0.], [0.]])]
      block.register_additional_tower(inputs, outputs)

      grads = [output**2 for output in outputs]
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)

  def testInstantiateFactorsSingleTensors(self):
    with tf.Graph().as_default():
      tf.set_random_seed(200)

      vocab_size = 5
      block = fb.FullyConnectedMultiIndepFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True,
          num_uses=2)

      inputs = tf.constant([[0, 1], [1, 2], [2, 3]])
      inputs.one_hot_depth = vocab_size
      outputs = tf.constant([[0.], [1.], [2.]])
      block.register_additional_tower(inputs, outputs)

      grads = outputs**2
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)

  def testMultiplyInverse(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)

      vocab_size = 5
      block = fb.FullyConnectedMultiIndepFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True)

      inputs = [tf.constant([[0, 1], [1, 2], [2, 3]]),
                tf.constant([[0, 0], [0, 0], [0, 4]])]
      for input in inputs:
        input.one_hot_depth = vocab_size
      outputs = [tf.constant([[0.], [1.], [2.]]),
                 tf.constant([[0.1], [0.], [0.]])]
      block.register_additional_tower(inputs, outputs)

      grads = [output**2 for output in outputs]
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)

      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Create a sparse update.
      indices = tf.constant([1, 3, 4])
      values = tf.constant([[1.], [1.], [1.]])
      sparse_vector = tf.IndexedSlices(
          values, indices, dense_shape=[vocab_size, 1])
      dense_vector = tf.reshape([0., 1., 0., 1., 1.], [vocab_size, 1])

      # Compare Fisher-vector product against explicit result.
      result = block.multiply_inverse(sparse_vector)
      expected_result = tf.matrix_solve(block.full_fisher_block(), dense_vector)

      sess.run(tf.global_variables_initializer())
      self.assertAlmostEqual(
          sess.run(expected_result[1]), sess.run(result.values[0]))
      self.assertAlmostEqual(
          sess.run(expected_result[3]), sess.run(result.values[1]))
      self.assertAlmostEqual(
          sess.run(expected_result[4]), sess.run(result.values[2]))

  def testMultiplyInverseSparse(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)

      vocab_size = 5
      block = fb.FullyConnectedMultiIndepFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True)

      inputs = [tf.constant([[0, 1], [1, 2], [2, 3]]),
                tf.constant([[0, 0], [0, 0], [0, 4]])]
      for input in inputs:
        input.one_hot_depth = vocab_size
      outputs = [tf.constant([[0.], [1.], [2.]]),
                 tf.constant([[0.1], [0.], [0.]])]
      block.register_additional_tower(inputs, outputs)

      grads = [output**2 for output in outputs]
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)

      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Create a sparse update.
      indices = tf.constant([1, 3, 4])
      values = tf.constant([[1.], [1.], [1.]])
      sparse_vector = tf.IndexedSlices(
          values, indices, dense_shape=[vocab_size, 1])
      dense_vector = tf.reshape([0., 1., 0., 1., 1.], [vocab_size, 1])

      # Compare Fisher-vector product against explicit result.
      result = block.multiply_inverse(sparse_vector)
      expected_result = tf.matrix_solve(block.full_fisher_block(), dense_vector)

      sess.run(tf.global_variables_initializer())
      self.assertAlmostEqual(
          sess.run(expected_result[1]), sess.run(result.values[0]))
      self.assertAlmostEqual(
          sess.run(expected_result[3]), sess.run(result.values[1]))
      self.assertAlmostEqual(
          sess.run(expected_result[4]), sess.run(result.values[2]))

  def testMultiplyInverseDense(self):
    with tf.Graph().as_default(), self.test_session() as sess:
      tf.set_random_seed(200)

      block = fb.FullyConnectedMultiIndepFB(
          lc.LayerCollection(),
          diagonal_approx_for_input=True)

      inputs = [tf.constant([[0., 1], [1, 2], [2, 3]]),
                tf.constant([[0., 0], [0, 0], [0, 4]])]
      outputs = [tf.constant([[0.], [1.], [2.]]),
                 tf.constant([[0.1], [0.], [0.]])]
      block.register_additional_tower(inputs, outputs)

      grads = [output**2 for output in outputs]
      damping = tf.constant(0.)
      block.instantiate_factors(((grads,),), damping)

      block._input_factor.instantiate_cov_variables()
      block._output_factor.instantiate_cov_variables()
      block.register_inverse()
      block._input_factor.instantiate_inv_variables()
      block._output_factor.instantiate_inv_variables()

      # Create a dense update.
      dense_vector = tf.constant([[0.5], [0.5]])

      # Compare Fisher-vector product against explicit result.
      result = block.multiply_inverse(dense_vector)
      expected_result = tf.matrix_solve(block.full_fisher_block(), dense_vector)

      sess.run(tf.global_variables_initializer())
      self.assertAlmostEqual(
          sess.run(expected_result[0]), sess.run(result[0]))
      self.assertAlmostEqual(
          sess.run(expected_result[1]), sess.run(result[1]))


def as_tensors(tensor_or_tuple):
  """Converts a potentially nested tuple of np.array to Tensors."""
  if isinstance(tensor_or_tuple, (tuple, list)):
    return tuple(as_tensors(t) for t in tensor_or_tuple)
  return tf.convert_to_tensor(tensor_or_tuple)


if __name__ == '__main__':
  tf.test.main()
