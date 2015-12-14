# coding=utf-8
"""
© 2016 LinkedIn Corp. All rights reserved.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""
import numpy as np

from luminol import exceptions
from luminol.algorithms.anomaly_detector_algorithms import AnomalyDetectorAlgorithm
from luminol.utils import qbinom, pbinom
from luminol.modules.time_series import TimeSeries


class SignTest(AnomalyDetectorAlgorithm):
  """
  In this algorithm, a sign test is performed by comparing data points to the baseline.
  The baseline can be adjusted with an offset and a percent gain. How it works:
  The data is compared within a fixed window and if the results differ significantly from random
  then all points in that window are considered to be an anomaly.

  A confidence is used for the statistical null test, 0.01 is the default p_value

  The entire time series is scanned with a sliding window and all points are scored.

  This algorithm assumes that time_series and baseline_time_series are perfectly aligned, meaning that:
   a) every timestamp that exists in time_series also exists in baseline_time_series
   b) lengths of both time series are same
   c) the test window must not be larger than the time series
  """
  def __init__(self, time_series, baseline_time_series,
               percent_threshold_upper=None,
               percent_threshold_lower=None,
               shift=None,
               scan_window=None,
               confidence=0.01):
    """
    :param time_series: current time series
    :param baseline_time_series: baseline time series
    :param percent_threshold_upper: If time_series is larger than baseline_time_series by this percent, then its
    a candidate for an anomaly
    :param percent_threshold_lower: If time_series is smaller than baseline_time_series by this percent, then its
    a candidate for an anomaly
    :param shift: baseline will be adjusted by this amount prior to computing percentage
                 TimeSeries > shift +  (1 + percent_threshold_upper/100) * Baseline
                 or for lower value
                 TimeSeries < shift +  (1 + percent_threshold_lower/100) * Baseline

    :param scan_window: number of data points to evaluate for anomalies
    :param confidence: Confidence to use for determining anomaly, default is 0.01
    :return:
    """
    super(SignTest, self).__init__(self.__class__.__name__, time_series, baseline_time_series)
    self.percent_threshold_upper = percent_threshold_upper
    self.percent_threshold_lower = percent_threshold_lower
    self.shift = shift
    self.scan_window = scan_window
    self.confidence = confidence

    if not self.percent_threshold_upper and not self.percent_threshold_lower and not self.shift:
      raise exceptions.RequiredParametersNotPassed('luminol.algorithms.anomaly_detector_algorithms.sign_test: \
          Either percent_threshold_upper or percent_threshold_lower or shift is needed')

    if not self.scan_window:
      raise exceptions.RequiredParametersNotPassed('luminol.algorithms.anomaly_detector_algorithms.sign_test: \
          scan window size needs to be specified')

    if not shift:
      self.shift = 0.0

  def _set_scores(self):
    """
    Compute anomaly scores for the time series
    anomaly regions are computed with sign test which also assigns a liklihood
    to the entire region
    """

    scores = np.zeros(len(self.time_series.values))

    if self.percent_threshold_upper is not None:
      anomalies = SignTest._rolling_sign_test(np.array(self.time_series.values),
                                              np.array(self.baseline_time_series.values),
                                              k=self.scan_window,
                                              conf=self.confidence,
                                              alpha=float(self.percent_threshold_upper) / 100,
                                              shift=self.shift)
      for (s, e), prob in anomalies:
        scores[s:e] = 100 * prob

    if self.percent_threshold_lower is not None:
      anomalies = SignTest._rolling_sign_test(-np.array(self.time_series.values),
                                    -np.array(self.baseline_time_series.values),
                                    k=self.scan_window,
                                    conf=self.confidence,
                                    alpha=float(self.percent_threshold_lower) / 100,
                                    shift=-self.shift)
      for (s, e), prob in anomalies:
        scores[s:e] = 100 * prob

    scores_dict = dict()
    for i, timestamp in enumerate(self.time_series.timestamps):
      scores_dict[timestamp] = scores[i]

    self.anom_scores = TimeSeries(scores_dict)

  @staticmethod
  def _merge_ranges(ranges, max_gap):
    """
    Merge ranges which are closer than max_gap
    :param ranges: assumed to be sorted on start
    :param max_gap: allowed gap between ranges
    :return:
    """
    merged_ranges = []
    for range in ranges:
      if merged_ranges:
        curr_start, curr_end = range
        # compare against last interval in merged_ranges
        pre_start, pre_end = merged_ranges[-1]
        if curr_start - pre_end < max_gap:
          # merge current range with the last range in the list
          merged_ranges[-1] = (pre_start, max(curr_end, pre_end))
        else:
          # append the new range to current one
          merged_ranges.append(range)
      else:
        # no merged ranges - just add this one
        merged_ranges.append(range)

    return merged_ranges

  @staticmethod
  def _rolling_sign_test(x, y, k=24, alpha=0.05, shift=0.0, conf=0.01, gap=0):
    """
    sign test ccompares x to y counts how many are over
    do a rolling comparison over all x , y
    x is compared against shift + alpha * y
    :param x: values to be compared
    :param y: values to compared against
    :param k: how many values to compare default is 24 (5 minute intervals * 2 hours)
    :param alpha scaling for y in percents 0.5 = 5% increase
    :param shift: amount to shift baseline by
    :param conf: likelihood to use for anomaly
    :param gap: allowed gap between anomalies
    """

    if len(x) != len(y) or len(x) < k:
      return np.zeros(len(x))

    # our filter to convolve with - just counts
    f = np.ones(k)

    # threshold to be bigger than
    qthresh = qbinom(1 - conf, k) - 1

    # this is 1 if bigger 0 otherwise
    d = np.fmax(np.sign(x - shift - (1. + alpha) * y), 0)

    con = np.convolve(f, d, mode='valid')

    a = np.fmax(con - qthresh, 0)

    ranges = [(t[0], t[0] + k) for t in np.argwhere(a)]

    ranges = SignTest._merge_ranges(ranges, gap)

    # compute score
    probs = list()
    for s, e in ranges:
      count = sum(d[s:e])
      probs.append(pbinom(count, e - s))

    # compute confidence
    return zip(ranges, probs)