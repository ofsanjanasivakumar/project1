import cv2
import numpy as np
import copy
import torch
from torchvision import transforms
from PIL import Image
import matplotlib.pyplot as plt
from dehazetransformer import DehazeFormer 
from a3_dehazing_model import Dehazer
from a2_cnn_model import DehazeCNN
class image_dehazer(): #math algo
    def __init__(self, airlightEstimation_windowSze=15, boundaryConstraint_windowSze=3, C0=20, C1=300,
                 regularize_lambda=0.1, sigma=0.5, delta=0.85, showHazeTransmissionMap=True):
        self.airlightEstimation_windowSze = airlightEstimation_windowSze
        self.boundaryConstraint_windowSze = boundaryConstraint_windowSze
        self.C0 = C0
        self.C1 = C1
        self.regularize_lambda = regularize_lambda
        self.sigma = sigma
        self.delta = delta
        self.showHazeTransmissionMap = showHazeTransmissionMap
        self._A = []
        self._transmission = []
        self._WFun = []
    def __AirlightEstimation(self, HazeImg):
        if (len(HazeImg.shape) == 3):
            for ch in range(len(HazeImg.shape)):
                kernel = np.ones((self.airlightEstimation_windowSze, self.airlightEstimation_windowSze), np.uint8)
                minImg = cv2.erode(HazeImg[:, :, ch], kernel)
                self._A.append(int(minImg.max()))
        else:
            kernel = np.ones((self.airlightEstimation_windowSze, self.airlightEstimation_windowSze), np.uint8)
            minImg = cv2.erode(HazeImg, kernel)
            self._A.append(int(minImg.max()))
    def __BoundCon(self, HazeImg):
        if (len(HazeImg.shape) == 3):
            t_b = np.maximum((self._A[0] - HazeImg[:, :, 0].astype(float)) / (self._A[0] - self.C0),
                             (HazeImg[:, :, 0].astype(float) - self._A[0]) / (self.C1 - self._A[0]))
            t_g = np.maximum((self._A[1] - HazeImg[:, :, 1].astype(float)) / (self._A[1] - self.C0),
                             (HazeImg[:, :, 1].astype(float) - self._A[1]) / (self.C1 - self._A[1]))
            t_r = np.maximum((self._A[2] - HazeImg[:, :, 2].astype(float)) / (self._A[2] - self.C0),
                             (HazeImg[:, :, 2].astype(float) - self._A[2]) / (self.C1 - self._A[2]))
            MaxVal = np.maximum(t_b, t_g, t_r)
            self._Transmission = np.minimum(MaxVal, 1)
        else:
            self._Transmission = np.maximum((self._A[0] - HazeImg.astype(float)) / (self._A[0] - self.C0),
                                            (HazeImg.astype(float) - self._A[0]) / (self.C1 - self._A[0]))
            self._Transmission = np.minimum(self._Transmission, 1)
        kernel = np.ones((self.boundaryConstraint_windowSze, self.boundaryConstraint_windowSze), float)
        self._Transmission = cv2.morphologyEx(self._Transmission, cv2.MORPH_CLOSE, kernel=kernel)
    def __LoadFilterBank(self):
        KirschFilters = []
        KirschFilters.append(np.array([[-3, -3, -3], [-3, 0, 5], [-3, 5, 5]]))
        KirschFilters.append(np.array([[-3, -3, -3], [-3, 0, -3], [5, 5, 5]]))
        KirschFilters.append(np.array([[-3, -3, -3], [5, 0, -3], [5, 5, -3]]))
        KirschFilters.append(np.array([[5, -3, -3], [5, 0, -3], [5, -3, -3]]))
        KirschFilters.append(np.array([[5, 5, -3], [5, 0, -3], [-3, -3, -3]]))
        KirschFilters.append(np.array([[5, 5, 5], [-3, 0, -3], [-3, -3, -3]]))
        KirschFilters.append(np.array([[-3, 5, 5], [-3, 0, 5], [-3, -3, -3]]))
        KirschFilters.append(np.array([[-3, -3, 5], [-3, 0, 5], [-3, -3, 5]]))
        KirschFilters.append(np.array([[-1, -1, -1], [-1, 8, -1], [-1, -1, -1]]))
        return (KirschFilters)
    def __CalculateWeightingFunction(self, HazeImg, Filter):
        HazeImageDouble = HazeImg.astype(float) / 255.0
        if (len(HazeImg.shape) == 3):
            Red = HazeImageDouble[:, :, 2]
            d_r = self.__circularConvFilt(Red, Filter)
            Green = HazeImageDouble[:, :, 1]
            d_g = self.__circularConvFilt(Green, Filter)
            Blue = HazeImageDouble[:, :, 0]
            d_b = self.__circularConvFilt(Blue, Filter)
            return (np.exp(-((d_r ** 2) + (d_g ** 2) + (d_b ** 2)) / (2 * self.sigma * self.sigma)))
        else:
            d = self.__circularConvFilt(HazeImageDouble, Filter)
            return (np.exp(-((d ** 2) + (d ** 2) + (d ** 2)) / (2 * self.sigma * self.sigma)))
    def __circularConvFilt(self, Img, Filter):
        FilterHeight, FilterWidth = Filter.shape
        assert (FilterHeight == FilterWidth), 'Filter must be square in shape --> Height must be same as width'
        assert (FilterHeight % 2 == 1), 'Filter dimension must be a odd number.'
        filterHalsSize = int((FilterHeight - 1) / 2)
        rows, cols = Img.shape
        PaddedImg = cv2.copyMakeBorder(Img, filterHalsSize, filterHalsSize, filterHalsSize, filterHalsSize,
                                       borderType=cv2.BORDER_WRAP)
        FilteredImg = cv2.filter2D(PaddedImg, -1, Filter)
        Result = FilteredImg[filterHalsSize:rows + filterHalsSize, filterHalsSize:cols + filterHalsSize]
        return (Result)
    def __CalTransmission(self, HazeImg):
        rows, cols = self._Transmission.shape
        KirschFilters = self.__LoadFilterBank()
        for idx, currentFilter in enumerate(KirschFilters):
            KirschFilters[idx] = KirschFilters[idx] / np.linalg.norm(currentFilter)
        WFun = []
        for idx, currentFilter in enumerate(KirschFilters):
            WFun.append(self.__CalculateWeightingFunction(HazeImg, currentFilter))
        tF = np.fft.fft2(self._Transmission)
        DS = 0
        for i in range(len(KirschFilters)):
            D = self.__psf2otf(KirschFilters[i], (rows, cols))
            DS = DS + (abs(D) ** 2)
        beta = 1
        beta_max = 2 ** 4
        beta_rate = 2 * np.sqrt(2)  
        while (beta < beta_max):
            gamma = self.regularize_lambda / beta
            DU = 0
            for i in range(len(KirschFilters)):
                dt = self.__circularConvFilt(self._Transmission, KirschFilters[i])
                u = np.maximum((abs(dt) - (WFun[i] / (len(KirschFilters) * beta))), 0) * np.sign(dt)
                DU = DU + np.fft.fft2(self.__circularConvFilt(u, cv2.flip(KirschFilters[i], -1)))
            self._Transmission = np.abs(np.fft.ifft2((gamma * tF + DU) / (gamma + DS)))
            beta = beta * beta_rate
        if (self.showHazeTransmissionMap):
            cv2.imshow("Haze Transmission Map", self._Transmission)
            cv2.waitKey(1)
    def __removeHaze(self, HazeImg):
        epsilon = 0.0001
        Transmission = pow(np.maximum(abs(self._Transmission), epsilon), self.delta)
        HazeCorrectedImage = copy.deepcopy(HazeImg)
        if (len(HazeImg.shape) == 3):
            for ch in range(len(HazeImg.shape)):
                temp = ((HazeImg[:, :, ch].astype(float) - self._A[ch]) / Transmission) + self._A[ch]
                temp = np.maximum(np.minimum(temp, 255), 0)
                HazeCorrectedImage[:, :, ch] = temp
        else:
            temp = ((HazeImg.astype(float) - self._A[0]) / Transmission) + self._A[0]
            temp = np.maximum(np.minimum(temp, 255), 0)
            HazeCorrectedImage = temp
        return (HazeCorrectedImage)
    def __psf2otf(self, psf, shape):
        if np.all(psf == 0):
            return np.zeros_like(psf)
        inshape = psf.shape
        psf = self.__zero_pad(psf, shape, position='corner')
        for axis, axis_size in enumerate(inshape):
            psf = np.roll(psf, -int(axis_size / 2), axis=axis)
        otf = np.fft.fft2(psf)
        n_ops = np.sum(psf.size * np.log2(psf.shape))
        otf = np.real_if_close(otf, tol=n_ops)
        return otf
    def __zero_pad(self, image, shape, position='corner'):
        shape = np.asarray(shape, dtype=int)
        imshape = np.asarray(image.shape, dtype=int)
        if np.all(imshape == shape):
            return image
        if np.any(shape <= 0):
            raise ValueError("ZERO_PAD: null or negative shape given")
        dshape = shape - imshape
        if np.any(dshape < 0):
            raise ValueError("ZERO_PAD: target size smaller than source one")
        pad_img = np.zeros(shape, dtype=image.dtype)
        idx, idy = np.indices(imshape)
        if position == 'center':
            if np.any(dshape % 2 != 0):
                raise ValueError("ZERO_PAD: source and target shapes "
                                 "have different parity.")
            offx, offy = dshape // 2
        else:
            offx, offy = (0, 0)
        pad_img[idx + offx, idy + offy] = image
        return pad_img
    def remove_haze(self, HazeImg):
        self.__AirlightEstimation(HazeImg)
        self.__BoundCon(HazeImg)
        self.__CalTransmission(HazeImg)
        haze_corrected_img = self.__removeHaze(HazeImg)
        HazeTransmissionMap = self._Transmission
        return (haze_corrected_img, HazeTransmissionMap)
def remove_haze(HazeImg, airlightEstimation_windowSze=15, boundaryConstraint_windowSze=3, C0=20, C1=300,
                regularize_lambda=0.1, sigma=0.5, delta=0.85, showHazeTransmissionMap=True):
    Dehazer = image_dehazer(airlightEstimation_windowSze=airlightEstimation_windowSze,
                            boundaryConstraint_windowSze=boundaryConstraint_windowSze, C0=C0, C1=C1,
                            regularize_lambda=regularize_lambda, sigma=sigma, delta=delta,
                            showHazeTransmissionMap=showHazeTransmissionMap)
    HazeCorrectedImg, HazeTransmissionMap = Dehazer.remove_haze(HazeImg)
    return (HazeCorrectedImg, HazeTransmissionMap)

model_path = 'dehaze_cnn_model.h5' 
file_path = 'hellohaze.webp' #change input image here!
original_image = cv2.imread(file_path)
original_size = (original_image.shape[1], original_image.shape[0])
dehazer_cnn = DehazeCNN(model_path)
preprocessed_image = dehazer_cnn.preprocess_image(file_path)
hazey= dehazer_cnn.predict(preprocessed_image,original_size, save_path='hazey.jpg')
dehazer_model = Dehazer()
HazeImg = np.array(dehazer_model.dehaze_image('hazey.jpg'))
dehazer = image_dehazer()
HazeCorrectedImg, HazeTransmissionMap = dehazer.remove_haze(HazeImg)
haze_for_days = cv2.imread(file_path)
def resize_with_aspect_ratio(image, target_size=64):
    original_h, original_w = image.shape[:2]
    scale = target_size / max(original_h, original_w)
    new_w = int(original_w * scale)
    new_h = int(original_h * scale)
    resized_image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.full((target_size, target_size, 3), 128, dtype=np.uint8)
    x_offset = (target_size - new_w) // 2
    y_offset = (target_size - new_h) // 2
    canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized_image
    return canvas
lab_img = cv2.cvtColor(HazeCorrectedImg, cv2.COLOR_BGR2LAB) #adjust brightness and colour
l, a, b = cv2.split(lab_img)
l = cv2.addWeighted(l, 1.3, np.zeros_like(l), 0, 10)
a = cv2.addWeighted(a, 1.1, np.zeros_like(a), 0, -10)
b = cv2.addWeighted(b, 1.1, np.zeros_like(b), 0, -10)
lab_adjusted = cv2.merge([l, a, b])
final_image = cv2.cvtColor(lab_adjusted, cv2.COLOR_LAB2BGR)
final_image_resized = resize_with_aspect_ratio(final_image, target_size=256)
cv2.imwrite("byehaze.jpg", final_image_resized)
cv2.imshow("Hazy Image", haze_for_days)
cv2.imshow("Dehazed Image", final_image_resized)
cv2.waitKey(0)
cv2.destroyAllWindows()