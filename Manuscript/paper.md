**BARC: Brain Atlas Regional Counter**

George Taylor^1^, Brenton T. Laing^1^

^1^Department of BioMolecular Sciences, University of Mississippi,
Oxford, MS 38673, U.S.A.

Correspondence should be addressed to Brenton Laing
(btlaing\@olemiss.edu)

**Summary**

Histological analysis of cells is a critical end-point for many
experiment types, particularly in neuroscience. One bottleneck in
histological analysis that consumes substantial experimenter effort, is
vulnerable to subjective decision-making, or unable to deal with the
heterogenous background signal present in brain tissue. Here we present
BARC, a semi-automated cell counting software specifically designed for
the use in brain tissue. The program is easy to install and launch as a
graphic user interface. Once launched, the user can follow intuitive
steps to paint regions of interest that correspond to the brain regions
they are want to generate counts for. With the press of a button, users
can analyze cell counts of any histological marker on their
2-dimensional image. The user has the ability to modify their settings
according to the signal to noise ratio in their acquisition, delete
erroneous identifications, and manually add cells that are undetected.
Once they are satisfied with the counts on an image, they can save
flattened image and generate spreadsheets corresponding to the regions
analyzed.

**1. Statement of Need**

Cell counting as part of the histological analysis of brain slices is a
valuable measure in neuroscience studies. This can be useful in
immunostaining^1^, tracing studies^3^, in-situ hybridization^4^. This
can be particularly useful for particularly for markers like c-FOS^2^
that have utility in assessing changes in neuronal activity patterns
following environmental stimuli, pharmacological treatment, or circuit
modulation. Together, these strategies are useful for localizing
transcripts or proteins on in-tact brain tissue as a measurement for
gene expression.

Cell counting is a critical bottleneck in the histological analysis
pipeline for many laboratories. This is particularly true of
neuroscience studies that often involve microscopy images of brain that
do not have uniform background level. Many software solutions have been
developed to address this analysis. For example, ImageJ^5^ is the most
used manual cell counting tool that is freely available. Macros have
been developed that semi-automate ImageJ analysis^6^. These macros have
gained popularity and coincidentally, multiple groups have developed
ImageJ tools named Autocount have been developed that attempt to
automate cell counting of fluorescent images^7,8^. These tools require
installation of macros and user modification to code proper thresholding
of signal for cell identification. These limitations hinder use uptake
and . Other groups have utilized machine learning based algorithms for
fungal cell counting under a complicated background^9^ for that research
field, but even the most complex images are still far more simpler than
neural tissue. Other tools such as Wholebrain^10^ and Belljar^11^ have
been developed for slice alignment and semi-automated cell detection,
but these require the user to take images of numerous sections that
contain the entire section. For many users, this requires tiling of many
images together, creates a huge acquisition time cost, and results in
the counting of many regions that are not experimentally needed. Thus,
many software solutions have been produced by none meet

Here, we present Brain Atlas Regional Counter (BARC), a stand-alone
semi-automated brain region histological analysis graphical user
interface (GUI). This software is packaged as an executable file for
simple implementation. It is open-source and released for any users to
make updates as they appropriate for their use case. The wide range of
settings available enable users to process images from any brain region
and type of cell-based histological analysis they need.

**2. Brief Description of Program Use and Features**

BARC is a software written in Python 3.14. It is available both as a
compiled EXE and as source code on the GitHub repository. The compiled
EXE allows for the program to be run without installing a python
environment or the required dependencies. Using the source code, the
program is tested to run on Windows and Linux, with plans to support OS
X. The dependencies utilized in this project include: Skimage and Scipy
for image analysis. Pillow is used for other image manipulation tasks
such as saving, resizing, and cropping. Numpy is used for mask
manipulation and assists in image processing. Tkinter is used as the GUI
framework. Fitz is used to handle the PDF format. Additional packages
are used, but the listed packages utilize the majority of processing
time.

The pipeline process is described by the workflow from data import, to
region setting, to cell detection and counting, and a save **(Figure
1)**. Once started, the program shows a blank screen with a menu bar.
The user is then able to import a .TIF image of the cells they would
like to count. The user is then able to adjust the brightness of the
image to improve visibility of the cells. This brightness feature was
designed so as not impact image processing.

Once the image is imported, the user is then able to isolate cell
regions either through a standardized PDF format digital atlas (e.g.
Paxinos and Franklin) or with manual painting and boundary drawing. The
user is then able to label each region of interest (ROI) that
corresponds to the structure. This structure identification function
allows users to conduct analysis of numerous brain regions within a
single image simultaneously, but does not require acquisition of the
entire brain slice. The region setting can be saved as a paint file that
can be viewed at a later time. This facilitates transparency but also
splitting of the user tasks between a region painter and counter to
enable counters with less anatomical knowledge to use regions that are
pre-drawn by an expert in identifying the brain structures of interest.
This separation of responsibility can also enable users to draw paint
regions from counterstains such as DAPI, NeuN, or Nissl staining for
blinded counting. A file splitter is available within the software for
users to split their image stacks to individual files.

The user is then able to visualize the cell mask to ensure that the
software settings are aligned with the expected cell count outputs.
These settings were designed to provide the user flexibility in setting
parameters for cell identification that are optimized for their imaging
configuration, signal to noise ratio, and staining techniques. The
software features a robust image processing settings menu to allow the
user to tune their image processing setup to best fit their needs. The
software also features an external settings configuration file, allowing
for the saving and sharing of settings. The processing settings include
options for background correction, noise reduction, contrast
enhancement, signal enhancement, and threshold method. The available
background correction methods are Tophat and Gaussian. The available
noise reduction methods are Gaussian, Median, and Bilateral. The
available contrast enhancement methods are Stretch, Clahe, and Gamma.
The available signal enhancement method is an Unsharpen mask. The
available thresholding methods are Otsu, Adaptive, Local, and Manual.
Other settings include Circularity, Sell Size, and Watershed
segmentation for overlapping cells.

Once the ROIs are set and the cell mask has been verified, the cell
counter can be started. It will automatically apply the cell mask and
count the total number of cells in each ROI. Users can add cells that
are missed by the mask using a manual counting step, or to subtract from
the mask that has counted portions of the image which are not cells.
This strategy provides the user with a way to substantially reduce the
total number of label clicks that they must apply, but still gives them
ultimate decision making ability for what is a cell and not a cell. The
software can automatically export the cell counts and a copy of the
flattened .TIF image with the ROIs and the tick marks over the counted
cells. The whole process only requires the user to use drop-down menus,
textboxes, radio-buttons, and clicks to conduct their analysis. This
strategy provides a simple process for transparent evaluation of counts
that is useful for evaluating and reporting results with record keeping
for painted regions of interest and the cells identified as counted
**(Figure 2)**.

The GitHub code repository contains detailed information about the
software not included here (<https://github.com/LaingLab/BARC>).

**Figures**

![](media\media\image1.png){width="6.5in" height="2.6347222222222224in"}

**Figure 1.** Workflow Diagram. This figure depicts data import steps
with a configuration load step, followed by import of the TIFF, and then
a choice between importing an atlas, drawing or importing painted
structures. The user can then select and label each region of interest,
followed by counting the cells through the semi-automated process. Once
satisfied with the counts, the user can save excel and the flattened
image.

![](media\media\image2.png){width="3.4069444444444446in"
height="3.19375in"}

Fig 2. Showing main workflow steps. A) Data Import B) Region Setting C)
Cell Detection/Counting D) Export Data

**References**

1 Tu, L. *et al.* Free-floating immunostaining of mouse brains. *Journal
of visualized experiments: JoVE*, 10-3791 (2021).2 Krukoff, T. L. in
*Cell neurobiology techniques* 213-230 (Springer, 1999).3 Wickersham, I.
R., Finke, S., Conzelmann, K.-K. & Callaway, E. M. Retrograde neuronal
tracing with a deletion-mutant rabies virus. *Nature methods* **4**,
47-49 (2007).4 Palop, J. J., Roberson, E. D. & Cobos, I. in
*Alzheimer\'s Disease and Frontotemporal Dementia: Methods and
Protocols* 207-230 (Springer, 2010).5 Sheffield, J. B. ImageJ, a useful
tool for biological image processing and analysis. *Microscopy and
Microanalysis* **13**, 200-201 (2007).6 Grishagin, I. V. Automatic cell
counting with ImageJ. *Analytical biochemistry* **473**, 63-65 (2015).7
Laing, B. T. *et al.* Regulation of body weight and food intake by AGRP
neurons during opioid dependence and abstinence in mice. *Frontiers in
Neural Circuits* **16**, 977642 (2022).8 Sharara, A., Kraft, C.,
Shameem, M. & Singh, B. N. AutoCount: An ImageJ Macro for Automatic Cell
Counting of Fluorescent Images. *DNA and Cell Biology Reports* **6**,
52-63 (2025).9 Li, C. *et al.* Machine learning‐based automated fungal
cell counting under a complicated background with ilastik and ImageJ.
*Engineering in Life Sciences* **21**, 769-777 (2021).10 Fürth, D. *et
al.* An interactive framework for whole-brain maps at cellular
resolution. *Nature neuroscience* **21**, 139-149 (2018).11 Soronow, A.
L. R., Jacobs, M. W., Dickson, R. G. & Kim, E. J. Bell Jar: A
Semiautomated Registration and Cell Counting Tool for Mouse
Neurohistology Analysis. *eneuro* **12** (2025).
