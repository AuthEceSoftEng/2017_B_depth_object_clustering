#!/usr/bin/env python
import sys
import rospy
import cv2
import yaml
import numpy as np
import time
from sensor_msgs.msg import Image, PointCloud2, CameraInfo
import sensor_msgs.point_cloud2 as pc2

from object_detector.msg import Detected_object
from cv_bridge import CvBridge, CvBridgeError
import gui_editor

class DetectedObject:
  def __init__(self, nameid, x, y, z, width, height):
    self.nameid = nameid
    self.x = x
    self.y = y
    self.z = z
    self.width = width
    self.height = height
    self.mu = (x,y,z)
    self.sigma = 1
    
    self.normalx = np.random.normal(x, width)
    self.normaly = np.random.normal(y, height)
  
  def __str__(self):
    string_to_print = 'Oject' + str(self.nameid) + ':(x:' + str(self.x) + ',y:' + str(self.y) + ',z:' + str(self.z) + ', width:' + str(self.width) +  ',height:' + str(self.height) + ')'
    return string_to_print
    
  def update_gaussdist(self, sigma, mu):
    self.mu = mu
    self.sigma = sigma

class image_capturer:  
  def __init__(self):
    self.rgb_sub = rospy.Subscriber("/camera/rgb/image_color", Image, self.Rgbcallback)
    self.dpth_sub = rospy.Subscriber("/camera/depth_registered/image", Image, self.Depthcallback)
    self.pcl_sub = rospy.Subscriber("/camera/depth_registered/points", PointCloud2, self.PointcloudCallback)
    self.dpth_raw_sub = rospy.Subscriber("/camera/depth_registered/image_raw", Image, self.Rawdepthcallback)
    self.camera_info_sub = rospy.Subscriber("camera/rgb/camera_info", CameraInfo, self.CameraInfocallback)
    # TODO subscribe only once
    
    self.obje_pub = rospy.Publisher('/object_found', Detected_object, queue_size=10)
    self.bridge = CvBridge()
    self.desired_shape = (480, 640) # initial shape
    # Divide it by a number, to scale the image and make computations faster.
    self.desired_shape = map(lambda x: x/2, self.desired_shape)
    
    self.rgbimg = np.ndarray(shape=self.desired_shape, dtype = np.uint8)
    self.depthimg = np.ndarray(shape=self.desired_shape, dtype = np.uint8)
    self.depthrawimg = np.ndarray(shape=self.desired_shape, dtype = np.uint8)
    self.pcl = PointCloud2()
    # Stores the overall objects that have been found.
    self.detected_objects = []
    # Stores the objects that have been found in the current frame.
    self.newly_detected_objects = []
    print "\nPress R if you want to trigger GUI for object detection..."
    print "Press Esc if you want to end the suffer of this node...\n"
    
    # Read the parameters from the yaml file
    with open("../cfg/conf.yaml", 'r') as stream:
      try:
        doc = yaml.load(stream)
        self.depth_weight = doc["clustering"]["depth_weight"]
        self.coordinates_weight = doc["clustering"]["coordinates_weight"]
        self.nclusters = doc["clustering"]["number_of_clusters"]
        self.depth_thresup = doc["clustering"]["depth_thresup"]
        self.depth_thresdown = doc["clustering"]["depth_thresdown"]
      except yaml.YAMLError as exc:
        print(exc) 
  
  def CameraInfocallback(self, msg_info):
    self.cx_d = msg_info.K[2]
    self.cy_d = msg_info.K[5]
    self.fx_d = msg_info.K[0]
    self.fy_d = msg_info.K[4]
  
  def Rgbcallback(self,msg_rgb):
    try:
      cv_image = self.bridge.imgmsg_to_cv2(msg_rgb, desired_encoding="passthrough")
      # Resize to the desired size
      cv_image_resized = cv2.resize(cv_image, tuple(reversed(self.desired_shape)), interpolation = cv2.INTER_AREA)
      self.rgbimg = cv_image_resized
      try:
        img = np.concatenate((self.rgbimg, cv2.cvtColor(self.depthimg,cv2.COLOR_GRAY2RGB)), axis=1)
        cv2.imshow("Combined image from my node", img)
      except ValueError as valerr:
        print "Images from channels are not ready yet..."
      k = cv2.waitKey(1) & 0xFF
      if k == 114: # if you press r, trigger the procressing
        self.Process()
        print "\nPress R if you want to trigger GUI for object detection..."
        print "Press Esc if you want to end the suffer of this node...\n"
      if k == 27: # if you press Esc, kill the node
        rospy.signal_shutdown("Whatever")
    except CvBridgeError as e:
      print(e)

  def Depthcallback(self,msg_depth): # TODO still too noisy!
    try:
      # The depth image is a single-channel float32 image
      # the values is the distance in mm in z axis
      cv_image = self.bridge.imgmsg_to_cv2(msg_depth, "32FC1")
      # Convert the depth image to a Numpy array since most cv2 functions
      # require Numpy arrays.
      cv_image_array = np.array(cv_image, dtype = np.float64)
      # Normalize the depth image to fall between 0 (black) and 1 (white) in order to view result
      # Normalize the depth image to fall between 0 (black) and 255 (white) in order to write result
      # http://docs.ros.org/electric/api/rosbag_video/html/bag__to__video_8cpp_source.html lines 95-125
      cv_image_norm_write = cv_image_array.copy()
      cv_image_norm_write = cv2.normalize(cv_image_array, cv_image_norm_write, 0, 255, cv2.NORM_MINMAX)
      # Resize to the desired size
      cv_image_resized_write = cv2.resize(cv_image_norm_write, tuple(reversed(self.desired_shape)), interpolation = cv2.INTER_AREA)
      self.depthimg = cv_image_resized_write.astype(np.uint8)
    except CvBridgeError as e:
      print(e)
  
  def Rawdepthcallback(self,msg_raw_depth): # TODO remove it, unless you need it for better depth image!
    # Raw image from device. Contains uint16 depths in mm.
    tempimg = self.bridge.imgmsg_to_cv2(msg_raw_depth, "16UC1")
    self.depthrawimg = cv2.resize(tempimg, tuple(reversed(self.desired_shape)), interpolation = cv2.INTER_AREA)
  
  def UpdatheworldCallback(self):
    # For every new object that was found, send it to the tf2_broadcaster
    for det_object in self.newly_detected_objects:
      msg = Detected_object()
      msg.nameid = det_object.nameid
      msg.x = det_object.x
      msg.y = det_object.y
      msg.z = det_object.z
      msg.width = det_object.width
      msg.height = det_object.height
      self.obje_pub.publish(msg)
    # Empty the list newly_detected_objects
    del self.newly_detected_objects[:]
  
  def Process(self):
    bounding_boxes = gui_editor.gui_editor(self.rgbimg, self.depthimg)
    counter = len(self.detected_objects)
    # For every newly found object.
    for c in bounding_boxes:
      x, y, w, h = cv2.boundingRect(c)
      # TODO identify the same objects and update them
      # Take the center of the bounding box of the object.
      centerx = x + w/2
      centery = y + h/2
      # Get the point from point cloud of the corresponding pixel.
      # Multiply by 2 the pixel's position, because I have resized-scaled the images by 2. 
      coords = self.return_pcl(centerx * 2, centery * 2, self.pcl)
      # Based on formula: x3D = (x * 2 - self.cx_d) * z3D/self.fx_d
      # Based on formula: y3D = (y * 2 - self.cy_d) * z3D/self.fy_d
      real_width = 2 * w * coords[2]/self.fx_d
      real_height = 2 * h * coords[2]/self.fy_d
      
      # TODO take into mind that there going to be some gaps in the objects
      #      a fix would be to take the median value of the bounding box
      #      self.depthrawimg[y][x] * 0.001 = coords[2]
      det_object = DetectedObject(counter, coords[0], coords[1], coords[2], real_width, real_height)
      self.detected_objects.append(det_object)
      self.newly_detected_objects.append(det_object)
      counter += 1
    self.UpdatheworldCallback()
    
  def PointcloudCallback(self,msg_pcl):
    self.pcl = msg_pcl
    
  def return_pcl(self, x_img, y_img, pcl) :
    if (y_img >= pcl.height) or (x_img >= pcl.width):
        return -1
    data_out = list(pc2.read_points(pcl, field_names=("x", "y", "z"), skip_nans=True, uvs=[[x_img, y_img]]))
    int_data = data_out[0]
    return int_data
    
  
def main(args):
  ic = image_capturer()
  rospy.init_node('image_capturer', anonymous=True)
  try:
    rospy.spin()
  except KeyboardInterrupt:
    print("Shutting down")
  cv2.destroyAllWindows()

if __name__ == '__main__':
  main(sys.argv)
