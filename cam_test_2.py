import time
import cv2
from facebank import load_facebank, prepare_facebank
from face_model import MobileFaceNet, l2_norm
from MTCNN import create_mtcnn_net
from utils.align_trans import *
from utils.util import *
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from torchvision import transforms as trans
import torch
import argparse
import sys
import os
sys.path.append(os.path.join(sys.path[0], 'MTCNN'))


def resize_image(img, scale):
    """
        resize image
    """
    height, width, channel = img.shape
    new_height = int(height * scale)     # resized new height
    new_width = int(width * scale)       # resized new width
    new_dim = (new_width, new_height)
    img_resized = cv2.resize(
        img, new_dim, interpolation=cv2.INTER_LINEAR)      # resized image
    return img_resized


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='face detection demo')
    parser.add_argument(
        '-th', '--threshold', help='threshold score to decide identical faces', default=60, type=float)
    parser.add_argument("-u", "--update", help="whether perform update the facebank",
                        action="store_true", default=False)
    parser.add_argument("-tta", "--tta", help="whether test time augmentation",
                        action="store_true", default=False)
    parser.add_argument(
        "-c", "--score", help="whether show the confidence score", action="store_true", default=True)
    parser.add_argument("--scale", dest='scale',
                        help="input frame scale to accurate the speed", default=0.5, type=float)
    parser.add_argument('--mini_face', dest='mini_face', help="Minimum face to be detected. derease to increase accuracy. Increase to increase speed",
                        default=20, type=int)
    args = parser.parse_args()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    # embeding size is 512 (feature vector)
    detect_model = MobileFaceNet(512).to(device)
    detect_model.load_state_dict(torch.load(
        'Weights/MobileFace_Net', map_location=lambda storage, loc: storage))
    print('MobileFaceNet face detection model generated')
    detect_model.eval()

    if args.update:
        targets, names = prepare_facebank(
            detect_model, path='facebank', tta=args.tta)
        print('facebank updated')
    else:
        targets, names = load_facebank(path='facebank')
        print('facebank loaded')
        # targets: number of candidate x 512

    cap = cv2.VideoCapture('http://root:xs12345678@10.10.10.186/video1s1.mjpg')
    while True:
        isSuccess, frame = cap.read()
        if isSuccess:
            try:
                start_time = time.time()
                input = resize_image(frame, args.scale)
                bboxes, landmarks = create_mtcnn_net(input, args.mini_face, device, p_model_path='MTCNN/weights/pnet_Weights',
                                                     r_model_path='MTCNN/weights/rnet_Weights',
                                                     o_model_path='MTCNN/weights/onet_Weights')

                # if bboxes != []:   DeprecationWarning: elementwise comparison failed; this will raise an error in the future. if bboxes != []:
                if len(bboxes) > 0:  # 避免76行 error
                    bboxes = bboxes / args.scale
                    landmarks = landmarks / args.scale

                faces = Face_alignment(
                    frame, default_square=True, landmarks=landmarks)

                embs = []

                test_transform = trans.Compose([
                    trans.ToTensor(),
                    trans.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])])

                for img in faces:
                    if args.tta:
                        mirror = cv2.flip(img, 1)
                        emb = detect_model(test_transform(
                            img).to(device).unsqueeze(0))
                        emb_mirror = detect_model(
                            test_transform(mirror).to(device).unsqueeze(0))
                        embs.append(l2_norm(emb + emb_mirror))
                    else:
                        embs.append(detect_model(
                            test_transform(img).to(device).unsqueeze(0)))

                if len(embs) > 0:  # 檢查 embs 列表是否非空
                    # number of detected faces x 512
                    source_embs = torch.cat(embs)
                    # i.e. 3 x 512 x 1 - 1 x 512 x 2 = 3 x 512 x 2
                    diff = source_embs.unsqueeze(-1) - \
                        targets.transpose(1, 0).unsqueeze(0)
                    # number of detected faces x numer of target faces
                    dist = torch.sum(torch.pow(diff, 2), dim=1)
                    # min and idx for each row
                    minimum, min_idx = torch.min(dist, dim=1)
                    # if no match, set idx to -1
                    min_idx[minimum > ((args.threshold-156)/(-80))] = -1
                    score = minimum
                    results = min_idx

                    # convert distance to score dis(0.7,1.2) to score(100,60)
                    score_100 = torch.clamp(score*-80+156, 0, 100)

                    image = Image.fromarray(
                        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    draw = ImageDraw.Draw(image)
                    font = ImageFont.truetype('utils/simkai.ttf', 30)

                    FPS = 1.0 / (time.time() - start_time)
                    draw.text((10, 10), 'FPS: {:.1f}'.format(
                        FPS), fill=(0, 0, 0), font=font)

                    for i, b in enumerate(bboxes):
                        draw.rectangle([(b[0], b[1]), (b[2], b[3])],
                                       outline='blue', width=5)
                        if args.score:
                            draw.text((int(b[0]), int(b[1]-25)), names[results[i] + 1] +
                                      ' score:{:.0f}'.format(score_100[i]), fill=(255, 255, 0), font=font)
                        else:
                            draw.text(
                                (int(b[0]), int(b[1]-25)), names[results[i] + 1], fill=(255, 255, 0), font=font)
                            print(names[results[i] + 1])

                    for p in landmarks:
                        for i in range(5):
                            draw.ellipse(
                                [(p[i] - 2.0, p[i + 5] - 2.0), (p[i] + 2.0, p[i + 5] + 2.0)], outline='blue')

                    frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

                cv2.imshow('video', frame)

            except Exception as e:
                print(f"Detect error: {str(e)}")

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
