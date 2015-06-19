#/***********************************************************************
# * Licensed Materials - Property of IBM 
# *
# * IBM SPSS Products: Statistics Common
# *
# * (C) Copyright IBM Corp. 1989, 2014
# *
# * US Government Users Restricted Rights - Use, duplication or disclosure
# * restricted by GSA ADP Schedule Contract with IBM Corp. 
# ************************************************************************/

from __future__ import with_statement

"""STATS ADJUST WIDTHS extension command"""

__author__ =  'IBM SPSS, JKP'
__version__=  '1.1.2'

# history
# 25-jan-2013 original version
# 08-aug-2013 allow for variations in name casing
# 16-jan-2014 Correct help text, bugfix to VARIABLES=ALL
# 25-feb-2014 Avoid keeping files open in case very many files
# 03-mar-2014 Add numeric/string type mismatch table

helptext = """STATS ADJUST WIDTHS 
    VARIABLES=variable list WIDTH={MAX* | MIN | FIRST} MAXWIDTH=positive integer
    DSNAMEROOT = rootname EXACTWIDTH=positive integer
/FILES list of file names and wilcards and dataset names
/OUTFILE RESAVE={NO* | YES} SUFFIX = "string" DIRECTORY="directory specification"
    OVERWRITE={NO* | YES} CLOSE={NO* | YES}
/HELP

Example:
STATS ADJUST WIDTHS FILES=ds1 "c:/data/mydata.sav"
    VARIABLES = string1 string2 DSNAMEROOT=ds_ WIDTH=MAX
    /OUTFILE RESAVE=YES SUFFIX="_adj" OVERWRITE=YES
    CLOSE=NO.

This command adjusts the widths of string variables across datasets to be the same
for convenience in merging and similar operations.  After the adjustments, the
active dataset will be the last file that was processed.  Only files or datasets
that are modified are resaved.

The active file must have a dataset name in order to run this command.

All keywords and subcommands are optional excep FILES and VARIABLES.

The FILES subcommand lists the datasets or file specifications to modify.
The list can contain file names, file name wildcards such as "c:/data/x*.sav",
and dataset names that are assigned to data.  However, "*" is interpreted
as a reference to the active dataset, not as a wildcard.

If a file that is listed in a file specification is already open, it will be reopened, and
given a new dataset name, and any previous unsaved changes will be lost.
Datasets, of course, are not reopened.  A dataset name that is only declared,
of course, will not work.

VARIABLES lists one or more string variables whose widths will be made the
same for each variable across the files.  Each variable must exist in at least
one of the files.  If there is a numeric/string type mismatch, it is reported.

VARIABLES=ALL can be used to select all string variables.

WIDTH specifies how the widths should be adjusted.  Each variable's width is made
the same across the files in which it exists.  For MAX, the width will be the
largest found.  For MIN, it will be the smallest.  For FIRST, it will be the
width found in the first file.  In that case, the variables must all exist in
the first file.  Reducing the widths can, of course, result in loss of data.

MAXWIDTH can be specified to limit the width calculated by SIZE.

EXACTWIDTH can be specified to set all the variables to the same width.
If used, WIDTH is ignored, and MAXWIDTH cannot be specified.

If there is only one file/dataset to process, only MAXWIDTH or EXACTSIZE
can cause any string widths to change.

Files that are opened must be assigned a dataset name by this procedure.  
DSNAMEROOT, which defaults to "adjust_" is used as the prefix for each name, 
and the remainder of the name is a sequential number.  Inputs specified as 
dataset names are not affected.  If the generated dataset name is already 
in use, it is reassigned to this list, and the previous owner of the dataset 
name will, therefore, be closed.

By default, all the files are left open.  The OUTFILE subcommand allows for
different behavior.
RESAVE specifies whether a file that was opened is resaved to disk.
Datasets in the input list are only saved if DIRECTORY is used.  In
that case, the dataset name with an sav extension becomes the file name.

SUFFIX optionally specifies a suffix to be added to the file name root for the
saved file.  For example, a file opened as data.sav would be saved as
data_adjusted if SUFFIX="_adjusted".

By default, files are saved to the input directory.  DIRECTORY specifies
an alternative location for the saved files.  DIRECTORY will be created
if it does not exist.  The path up to the last portion must already exist.

OVERWRITE specifies whether the save tries to overwrite an existing file.
By default, files are not overwritten.

CLOSE specifies whether to close any file that was opened.  Using RESAVE=NO
with CLOSE=YES is not very useful.  The active dataset, if included, is not closed.
Note: If the number of files to process is large, it may be necessary to 
specify CLOSE=YES in order to avoid having an excessive number of files
open with possible resource exhaustion.

/HELP displays this help and does nothing else.
"""

import spss, spssaux
from extension import Template, Syntax, processcmd
import sys, locale, os.path, random, re, glob


def adjustwidths(filelist, varnames, width="max", maxwidth=None, exactwidth=None, resave=False, dsnameroot="adjust_",
    suffix="", overwrite=False, closeoption=False, directory=None):

    activedsname = spss.ActiveDataset()
    if activedsname == "*":
        raise ValueError(_("""The active dataset must have a dataset name in order to run this command"""))
    if maxwidth and exactwidth:
        maxwidth=None
    
    fh = spssaux.FileHandles()
    if directory:
        # recognize file handle definitions
        directory = fh.resolve(directory)
        if not os.path.exists(directory):
            os.mkdir(directory)  # only works one level down
    if directory and not os.path.isdir(directory):
        raise ValueError(_("""Specified output directory is not a directory: %s""") % directory) 
    if "all" in [item.lower() for item in varnames]:
        varnames = ["all"]   # preclude ALL + other variable names
    dsmanager = DatasetManager(dsnameroot, activedsname)
    filelist = expand(filelist, fh, dsmanager, activedsname)
    varmanager = VariablesManager(varnames, width, maxwidth, exactwidth)
    
    # collect variable information.  If a name is a dataset reference
    # it is used as is.  If it is a filespec, the file is opened and assigned
    # dataset name, its information is collected, and the dataset is closed
    
    errortable = NonProcPivotTable(omssubtype="ADJUSTWIDTHERRORS",
        outlinetitle = _("""Type Conflicts"""),
        tabletitle = _("""String-Numeric Type Conflicts"""),
        caption = _("""Only the first 20 errors are shown"""),
        rowdim = _("""Dataset or File Name"""),
        columnlabels=[_("""String Variables Numeric in a Previous File"""),
            _("""Numeric Variables String in a Previous File""")]
    )
    errorcount = 0
    
    for f in filelist:
        f = fh.resolve(f)  # convert to full form resolving any file handle
        if dsmanager.isdatasetname(f):
            dsmanager.dsmapper(f, None)
            errtype1, errtype2 = varmanager.getdsvarinfo(f)
        else:
            dsname = dsmanager.nextdsname()
            spss.Submit("""GET FILE="%(f)s".
DATASET NAME %(dsname)s.""" % locals())
            dsmanager.dsmapper(dsname, f)
            errtype1, errtype2 = varmanager.getdsvarinfo(dsname)
            if (closeoption):
                spss.Submit("""DATASET CLOSE %(dsname)s.""" % locals())
        if errtype1 or errtype2:
            errorcount += 1
            if errorcount <=20:
                errortable.addrow(f, [", ".join(errtype1), ", ".join(errtype2)])
    varmanager.calculatewidths()
    if errorcount > 0:
        errortable.generate()
    
    applywidths = ApplyWidths(varmanager, dsmanager, resave, suffix, overwrite, directory, closeoption)
    for ds in dsmanager.dsmap:
        applywidths.processdataset(ds)
        
    # It would be nice to reactivate the original active dataset, but if it was the
    # empty dataset nominally created when a job starts, it will be gone, so leaving
    # this to the user.


def expand(filelist, fh, dsmanager, activefile):
    """Expand wildcards and resolve file handles in a list of filespecs and datasets
    
    filelist is the list of items
    fh is a file handle object
    dsmanager is a DatasetManager object
    activefile is the dataset name of the active file (which must have one)"""
    
    filelistout = []
    for item in filelist:
        if item == "*":
            filelistout.append(activefile)
        elif dsmanager.isdatasetname(item):
            filelistout.append(item)
        else:
            item = fh.resolve(item)  # resolve any file handle
            expanded = glob.glob(item)   # expand wildcards
            if len(expanded) == 0:
                raise ValueError(_("""Specified file not found: %s""" % item))
            filelistout.extend(expanded)
    return filelistout
    
class DatasetManager(object):
    """Manage Statistics datasets"""
    
    def __init__(self, dsnameroot, activefile):
        """dsnameroot is the rootname for dataset generation"""
        
        self.dsnameroot = dsnameroot
        self.dscount = 0
        self.dsmap = {}  # dataset to filespec mapper
        self.activefile = activefile
        
        # get all existing dataset names
        # note that dataset names are not case sensitive
        randomname = "D" + str(random.random())
        spss.Submit("""oms /destination viewer=no xmlworkspace="%(randomname)s" format=oxml
/tag = "%(randomname)s".
dataset display.
omsend tag="%(randomname)s".""" % locals())
        self.existingdsnames = set([s.lower() for s in spss.EvaluateXPath(randomname, "/outputTree", 
            """//pivotTable[@subType="Datasets"]//cell/@text""")])
        spss.DeleteXPathHandle(randomname)
        
    def isdatasetname(self, name):
        """Return True if name is a known dataset name
        
        name is an input file specification or dataset name"""
        
        return re.split(r"[/\\]", name)[0].lower() in self.existingdsnames
    
    def nextdsname(self):
        """Return next generated dataset name"""
        
        self.dscount += 1
        return self.dsnameroot + str(self.dscount)
    
    def dsmapper(self, dsname, filespec):
        """Maintain dsname to filespec mapping
        
        filespec should be None if this is an original dataset name without a filename available"""
        
        self.dsmap[dsname] = filespec
    
class VariablesManager(object):
        """Manage the collections of variable information for multiple files or datasets"""
        def __init__(self, variables, width, maxwidth, exactwidth):
            """variables is the list of candidate variables to adjust.  "all" indicates all strings
            
            width is max, min, or first
            maxwidth is a constraint on size"""
            
            self.files = {}
            self.variables = variables
            self.width = width
            self.maxwidth = maxwidth
            self.exactwidth = exactwidth
            self.first = True
            self.varsfound = set()
            self.allnumerics = set()
            self.allstrings = set()
            
        def getdsvarinfo(self, dsname):
            """Get string variable and width information for dataset dsname
            
            If a specified or implied variable is not a string, it is ignored.
            The first call binds the variable instances used for method first.
            
            Returns True if a string/numeric type mismatch"""
            
            # side effect: dataset is activated
            if self.first:
                self.firstfile = dsname
                self.first = False
            spss.Submit("DATASET ACTIVATE " + dsname)
            if self.variables[0] == "all":
                vardict = spssaux.VariableDict()
            else:
                vardict = spssaux.VariableDict(self.variables)
            self.allnumerics.update(item.lower() for item in vardict.variablesf(variableType="numeric"))
            self.allstrings.update(item.lower for item in vardict.variablesf(variableType="string"))
            #if self.variables[0] == "all":
                #vardict = spssaux.VariableDict(variableType="string")
            #else:  # non-string variables are silently ignored
                #vardict = spssaux.VariableDict(self.variables, variableType="string")
            varprop = dict([(vardict[v].VariableName.lower(), vardict[v].VariableType)\
                for v in vardict.variables if vardict[v].VariableType != 0])
            self.files[dsname] = varprop
            #self.varsfound.update(vardict.variables)
            self.varsfound.update(varprop.keys())
            typemismatchsn = self.allnumerics.intersection(set(varprop.keys()))
            numerics = set([vardict[v].VariableName.lower() for v in vardict.variables\
                if vardict[v].VariableType == 0])
            typemismatchns = self.allstrings.intersection(numerics)

            return typemismatchsn, typemismatchns
                
        def calculatewidths(self):
            """Calculate the width to apply to each variable"""
            
            # calcwidths is a dictionary holding the calculated width with lower-cased varname as key
            if len(self.varsfound) == 0:
                raise ValueError(_("""None of the specified variables were found in any of the specified files"""))
            self.calcwidths = {}  # indexed by variable name
            if self.exactwidth:
                #for v in self.variables:
                for v in self.varsfound:
                    self.calcwidths[v.lower()] = self.exactwidth
            else:
                if self.width == "first":
                    self.calcwidths = self.files[self.firstfile]
                else:
                    if self.width == "max":
                        func = max
                    else:
                        func = min
                    #for v in self.variables:
                    for v in self.varsfound:
                        vl = v.lower()
                        calc = func([vw[vl] for vw in self.files.values() if vl in vw])
                        if self.maxwidth:
                            calc = min(calc, self.maxwidth)
                        self.calcwidths[vl] = calc
class ApplyWidths(object):
    """Apply calculated variable widths to file and process the file"""
    
    def __init__(self, widths, dataset, resave, suffix, overwrite, directory, close):
        """widths is a VariablesManager object
        dataset is a DatasetManagement object
        resave, suffix, directory, and close are the file processing options"""
    
        attributesFromDict(locals())
        
    def processdataset(self, ds):
        
        alterations = []
        for v, vw in self.widths.files[ds].items():
            vl = v.lower()
            try:
                if vw != self.widths.calcwidths[vl]:
                    alterations.append((v, self.widths.calcwidths[vl]))
            except:
                raise ValueError(_("""Using the "first" method, a variable was found in a later file
that is not present in the first file: %s""") % v)
                
        if alterations:
            # The item must be reopened if it is a file rather than a dataset
            # and the close option was specified
            if self.dataset.dsmap[ds] is not None and self.close:
                spss.Submit("""GET FILE="%s".
DATASET NAME %s.""" % (self.dataset.dsmap[ds], ds))
            cmd = "ALTER TYPE " + " ".join([v + " (A" + str(vw) + ")" for (v, vw) in alterations])
            spss.Submit("DATASET ACTIVATE " + ds)
            spss.Submit(cmd)
            if self.resave:  # the dataset must have a filespec
                self.save(ds)
            
    def save(self, ds):
        """Save dataset
        
        ds is the dataset name of the object to be saved
        If ds does not have an associated filespec, it is
        only saved if directory is used.  In that case, the
        filename will be the dataset name with an sav extension.
        
        Implements directory, suffix, and close options."""
        
        fspec = self.dataset.dsmap[ds]
        if fspec is None and self.directory is None:   # file is not saved
            return
        if fspec is not None:
            fdir, base = os.path.dirname(fspec), os.path.basename(fspec)
            if self.suffix:    # create file name with suffix preceding the extension
                parts = os.path.splitext(base)
                base = parts[0] + self.suffix + parts[1]  # if no extension, parts[1] wil be empty string
            if self.directory:   # substitute new location for original
                fdir = self.directory
            target = os.path.join(fdir, base)
        else:
            base = ds + os.path.extsep + "sav"
            target = os.path.join(self.directory, base)
        if not self.overwrite and os.path.exists(target):
            print _("""File %s already exists and will not be overwritten.""") % target
        else:
            # this is already the active file
            spss.Submit("""SAVE OUTFILE="%(target)s".""" % locals())
            # file might already be gone
            try:
                if self.close and not ds == self.dataset.activefile:
                    spss.Submit("DATASET CLOSE " + ds)  # file could remain open as active file
            except:
                pass
            
def Run(args):
    """Execute the STATS AJUST WIDTHS extension command"""

    args = args[args.keys()[0]]
    # debugging
    # makes debug apply only to the current thread
    #try:
        #import wingdbstub
        #if wingdbstub.debugger != None:
            #import time
            #wingdbstub.debugger.StopDebug()
            #time.sleep(2)
            #wingdbstub.debugger.StartDebug()
        #import thread
        #wingdbstub.debugger.SetDebugThreads({thread.get_ident(): 1}, default_policy=0)
        ## for V19 use
        ##    ###SpssClient._heartBeat(False)
    #except:
        #pass
    oobj = Syntax([
        Template("VARIABLES", subc="",  ktype="literal", var="varnames", islist=True),
        Template("WIDTH", subc="", ktype="str", var="width", vallist = ["max", "min", "first"], islist=False),
        Template("MAXWIDTH", subc="", ktype="int", var="maxwidth", vallist=(1,32767)),
        Template("EXACTWIDTH", subc="", ktype="int", var="exactwidth", vallist=(1, 32767)),
        Template("DSNAMEROOT", subc="", ktype="varname", var="dsnameroot"),
        Template("", subc="FILES",  ktype="literal", var="filelist", islist=True),
        Template("RESAVE", subc="OUTFILE", ktype="bool", var="resave", islist=False),
        Template("SUFFIX", subc="OUTFILE", ktype="literal", var="suffix"),
        Template("DIRECTORY", subc="OUTFILE", ktype="literal", var="directory"),
        Template("OVERWRITE", subc="OUTFILE", ktype="bool", var="overwrite"),
        Template("CLOSE", subc="OUTFILE", ktype="bool", var="closeoption"),
        Template("HELP", subc="", ktype="bool")])
    
    #enable localization
    global _
    try:
        _("---")
    except:
        def _(msg):
            return msg
    # A HELP subcommand overrides all else
    if args.has_key("HELP"):
        #print helptext
        helper()
    else:
        processcmd(oobj, args, adjustwidths)

def helper():
    """open html help in default browser window
    
    The location is computed from the current module name"""
    
    import webbrowser, os.path
    
    path = os.path.splitext(__file__)[0]
    helpspec = "file://" + path + os.path.sep + \
         "markdown.html"
    
    # webbrowser.open seems not to work well
    browser = webbrowser.get()
    if not browser.open_new(helpspec):
        print("Help file not found:" + helpspec)  
try:    #override
    from extension import helper
except:
    pass        
class NonProcPivotTable(object):
    """Accumulate an object that can be turned into a basic pivot table once a procedure state can be established"""
    
    def __init__(self, omssubtype, outlinetitle="", tabletitle="", caption="", rowdim="", coldim="", columnlabels=[],
                 procname="Messages"):
        """omssubtype is the OMS table subtype.
        caption is the table caption.
        tabletitle is the table title.
        columnlabels is a sequence of column labels.
        If columnlabels is empty, this is treated as a one-column table, and the rowlabels are used as the values with
        the label column hidden
        
        procname is the procedure name.  It must not be translated."""
        
        attributesFromDict(locals())
        self.rowlabels = []
        self.columnvalues = []
        self.rowcount = 0

    def addrow(self, rowlabel=None, cvalues=None):
        """Append a row labelled rowlabel to the table and set value(s) from cvalues.
        
        rowlabel is a label for the stub.
        cvalues is a sequence of values with the same number of values are there are columns in the table."""

        if cvalues is None:
            cvalues = []
        self.rowcount += 1
        if rowlabel is None:
            self.rowlabels.append(str(self.rowcount))
        else:
            self.rowlabels.append(rowlabel)
        self.columnvalues.extend(cvalues)
        
    def generate(self):
        """Produce the table assuming that a procedure state is now in effect if it has any rows."""
        
        privateproc = False
        if self.rowcount > 0:
            try:
                table = spss.BasePivotTable(self.tabletitle, self.omssubtype)
            except:
                StartProcedure(_("Adjust Widths"), self.procname)
                privateproc = True
                table = spss.BasePivotTable(self.tabletitle, self.omssubtype)
            if self.caption:
                table.Caption(self.caption)
            if self.columnlabels != []:
                table.SimplePivotTable(self.rowdim, self.rowlabels, self.coldim, self.columnlabels, self.columnvalues)
            else:
                table.Append(spss.Dimension.Place.row,"rowdim",hideName=True,hideLabels=True)
                table.Append(spss.Dimension.Place.column,"coldim",hideName=True,hideLabels=True)
                colcat = spss.CellText.String("Message")
                for r in self.rowlabels:
                    cellr = spss.CellText.String(r)
                    table[(cellr, colcat)] = cellr
            if privateproc:
                spss.EndProcedure()
                
def attributesFromDict(d):
    """build self attributes from a dictionary d."""
    self = d.pop('self')
    for name, value in d.iteritems():
        setattr(self, name, value)

def StartProcedure(procname, omsid):
    """Start a procedure
    
    procname is the name that will appear in the Viewer outline.  It may be translated
    omsid is the OMS procedure identifier and should not be translated.
    
    Statistics versions prior to 19 support only a single term used for both purposes.
    For those versions, the omsid will be use for the procedure name.
    
    While the spss.StartProcedure function accepts the one argument, this function
    requires both."""
    
    try:
        spss.StartProcedure(procname, omsid)
    except TypeError:  #older version
        spss.StartProcedure(omsid)